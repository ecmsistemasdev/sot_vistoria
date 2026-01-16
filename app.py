#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
============================================================
SISTEMA DE OPERAÇÕES DE TRANSPORTE - TJRO
============================================================
Versão: 2.1 (Sem WeasyPrint - Compatível com Windows)
============================================================
CORREÇÃO APLICADA:
- Removido WeasyPrint (requer GTK no Windows)
- Usando xhtml2pdf para geração de PDFs
- 100% compatível com Windows
============================================================
"""


# ============================================================
# IMPORTS - BIBLIOTECAS PYTHON PADRÃO
# ============================================================
import os
import json
import uuid
import base64
import re
import unicodedata
import time  # ✅ Módulo time para time.time()
from io import BytesIO
from datetime import datetime, timedelta  # ✅ SEM 'time' aqui!
from math import radians, cos, sin, asin, sqrt
from functools import wraps

# ============================================================
# IMPORTS - BIBLIOTECAS EXTERNAS
# ============================================================
# Threading é mais estável para desenvolvimento com debug=True
# NÃO precisa de monkey.patch_all()

from flask import (
    Flask, 
    render_template, 
    request, 
    make_response, 
    redirect, 
    url_for, 
    flash, 
    jsonify, 
    send_file, 
    session
)
from flask_caching import Cache
from flask_mysqldb import MySQL
import MySQLdb.cursors

from flask_mail import Mail, Message

from flask_socketio import (
    SocketIO, 
    emit, 
    join_room, 
    leave_room
)

from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
# ✅ REMOVIDO WeasyPrint (incompatível com Windows)
# Alternativa: usar xhtml2pdf ou ReportLab
from pytz import timezone
import PyPDF2
import airportsdata

# ============================================================
# INICIALIZAÇÃO DO FLASK
# ============================================================
app = Flask(__name__)

# ============================================================
# INICIALIZAR CACHE (DEPOIS DO APP)
# ============================================================
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# ============================================================
# CONFIGURAÇÕES DO SISTEMA
# ============================================================

# Segurança
app.secret_key = os.getenv('SECRET_KEY')

# Upload de arquivos
UPLOAD_FOLDER = '/tmp/uploads'
ALLOWED_EXTENSIONS = {'pdf'}


# ============================================================
# CONFIGURAÇÃO DO BANCO DE DADOS (MySQL)
# ============================================================
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')
app.config['MYSQL_CHARSET'] = 'utf8mb4'

mysql = MySQL(app)


# ============================================================
# CONFIGURAÇÃO DO EMAIL (Flask-Mail)
# ============================================================
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = os.getenv('MAIL_PORT')
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_MAX_EMAILS'] = None
app.config['MAIL_TIMEOUT'] = 10  # segundos

mail = Mail(app)


# ============================================================
# CONFIGURAÇÃO DO WEBSOCKET (Flask-SocketIO com Threading)
# ============================================================
# Threading é mais estável para desenvolvimento com debug=True
# Em produção, pode trocar para 'gevent' se necessário
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',  # ✅ Threading = estável + debug funciona!
    ping_timeout=60,
    ping_interval=25,
    logger=True,            # Ver logs para debug
    engineio_logger=False   # Reduzir verbosidade
)


# ============================================================
# DADOS EXTERNOS
# ============================================================
# Carregar dados dos aeroportos (código IATA)
airports = airportsdata.load('IATA')


# ============================================================
# VARIÁVEIS GLOBAIS DO WEBSOCKET
# ============================================================
# Store de conexões ativas (WebSocket)
usuarios_conectados = {}  # {sid: {'usuario': 'login', 'nome': 'Nome Completo'}}


# ============================================================
# DECORADORES E FUNÇÕES AUXILIARES
# ============================================================

def login_required(f):
    """
    Decorador para proteger rotas que exigem autenticação
    Redireciona para login se usuário não estiver autenticado
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_login' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def authenticated_only(f):
    """
    Decorador para proteger eventos WebSocket
    Rejeita conexões não autenticadas
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('usuario_login'):
            return False
        return f(*args, **kwargs)
    return wrapped


# ============================================================
# FUNÇÕES AUXILIARES - WEBSOCKET
# ============================================================

def emitir_alteracao_demanda(tipo_operacao, id_ad, dados_demanda=None):
    """
    Emite alteração de demanda para todos os clientes conectados via WebSocket
    
    Args:
        tipo_operacao (str): 'INSERT', 'UPDATE', 'DELETE'
        id_ad (int): ID da demanda
        dados_demanda (dict, optional): Dados completos da demanda
    """
    try:
        usuario_atual = session.get('usuario_login', '')
        
        payload = {
            'tipo': tipo_operacao,
            'entidade': 'DEMANDA',
            'id_ad': id_ad,
            'usuario': usuario_atual,
            'timestamp': datetime.now().isoformat()
        }
        
        if dados_demanda:
            payload['dados'] = dados_demanda
        
        # ===== CORREÇÃO: Remover skip_sid (não existe em rotas HTTP) =====
        socketio.emit('alteracao_agenda', payload, room='agenda')
        # Emite para TODOS na sala, incluindo quem fez a alteração
        # O frontend vai ignorar suas próprias alterações
        
        print(f"📡 WebSocket: Emitido {tipo_operacao} - ID_AD: {id_ad} por {usuario_atual}")
        
    except Exception as e:
        print(f"❌ Erro ao emitir alteração WebSocket: {str(e)}")
        import traceback
        traceback.print_exc()


def emitir_alteracao_diaria_terceirizado(tipo_operacao, iditem, id_ad, fl_email=None):
    """
    Emite alteração de diária de terceirizado via WebSocket
    
    Args:
        tipo_operacao (str): 'INSERT', 'UPDATE', 'DELETE'
        iditem (int): ID do item de diária
        id_ad (int): ID da demanda
        fl_email (str, optional): Flag de email ('S' ou 'N')
    """
    try:
        usuario_atual = session.get('usuario_login', '')
        
        payload = {
            'tipo': tipo_operacao,
            'entidade': 'DIARIA_TERCEIRIZADO',
            'iditem': iditem,
            'id_ad': id_ad,
            'usuario': usuario_atual,
            'timestamp': datetime.now().isoformat()
        }
        
        if fl_email is not None:
            payload['fl_email'] = fl_email
        
        # ===== CORREÇÃO: Remover skip_sid =====
        socketio.emit('alteracao_agenda', payload, room='agenda')
        
        print(f"📡 WebSocket: Emitido {tipo_operacao} DIÁRIA - IDITEM: {iditem}")
        
    except Exception as e:
        print(f"❌ Erro ao emitir alteração de diária: {str(e)}")
        import traceback
        traceback.print_exc()


# ============================================================
# FUNÇÕES AUXILIARES - UTILITÁRIOS
# ============================================================

def allowed_file(filename):
    """Verifica se extensão do arquivo é permitida"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def calcular_distancia_haversine(lat1, lon1, lat2, lon2):
    """
    Calcula distância entre dois pontos geográficos usando fórmula de Haversine
    
    Args:
        lat1, lon1: Latitude e longitude do ponto 1
        lat2, lon2: Latitude e longitude do ponto 2
    
    Returns:
        float: Distância em quilômetros
    """
    # Converter de graus para radianos
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    
    # Fórmula de Haversine
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Raio da Terra em km
    r = 6371
    
    return c * r


# ============================================================
# EVENTOS WEBSOCKET - CONEXÃO/DESCONEXÃO
# ============================================================

@socketio.on('connect')
def handle_connect():
    """Cliente se conecta ao WebSocket"""
    usuario_login = session.get('usuario_login')
    usuario_nome = session.get('usuario_nome', 'Usuário')
    
    if not usuario_login:
        print("⚠️  WebSocket: Conexão rejeitada - usuário não autenticado")
        return False  # Rejeitar conexão não autenticada
    
    # Armazenar conexão
    usuarios_conectados[request.sid] = {
        'usuario': usuario_login,
        'nome': usuario_nome,
        'connected_at': datetime.now().isoformat()
    }
    
    # Entrar na sala 'agenda' (todos os usuários da agenda ficam nesta sala)
    join_room('agenda')
    
    print(f"✅ WebSocket conectado: {usuario_nome} ({usuario_login}) - SID: {request.sid}")
    
    # Notificar outros usuários
    emit('usuario_conectou', {
        'usuario': usuario_nome,
        'total_conectados': len(usuarios_conectados)
    }, room='agenda', skip_sid=request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    """Cliente se desconecta do WebSocket"""
    if request.sid in usuarios_conectados:
        usuario_info = usuarios_conectados[request.sid]
        leave_room('agenda')
        del usuarios_conectados[request.sid]
        
        print(f"❌ WebSocket desconectado: {usuario_info['nome']} - SID: {request.sid}")
        
        # Notificar outros usuários
        emit('usuario_desconectou', {
            'usuario': usuario_info['nome'],
            'total_conectados': len(usuarios_conectados)
        }, room='agenda')


@socketio.on('ping')
@authenticated_only
def handle_ping():
    """Responde ao ping do cliente (keepalive)"""
    emit('pong', {'timestamp': datetime.now().isoformat()})


@app.route('/salvar-ordem-cronologica', methods=['POST'])
def salvar_ordem_cronologica():
    """
    Salva dados da Ordem Cronológica no banco de dados
    O envio para o Google Forms será feito via URL pré-preenchida no frontend
    """
    try:
        dados = request.json
        
        # ========================================
        # SALVAR NO BANCO DE DADOS
        # ========================================
        cursor = mysql.connection.cursor()
        
        sql_insert = """
            INSERT INTO ORDEM_CRONOLOGICA (
                NU_PROCESSO, DOC_COBRANCA, NM_FORNECEDOR, CPF_CNPJ,
                VL_CREDITO, DT_RECEBIMENTO, DT_PAGAMENTO, NU_CONTRATO,
                CAT_CONTRATO, VL_CONTRATO, TIPO_CONTRATO, GESTOR_CONTRATO,
                COMARCA_GESTOR, UNIDADE_GESTOR, NU_EMPENHO, ELEMENTO_DESPESA,
                UO, ENVIADO_GOOGLE_FORMS, DATA_ENVIO
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """
        
        valores = (
            dados.get('nu_processo'),
            dados.get('doc_cobranca'),
            dados.get('nm_fornecedor'),
            dados.get('cpf_cnpj'),
            float(dados.get('vl_credito', 0)),
            dados.get('dt_recebimento'),
            dados.get('dt_pagamento'),
            dados.get('nu_contrato'),
            dados.get('cat_contrato'),
            float(dados.get('vl_contrato', 0)),
            dados.get('tipo_contrato'),
            dados.get('gestor_contrato'),
            dados.get('comarca_gestor'),
            dados.get('unidade_gestor'),
            dados.get('nu_empenho'),
            dados.get('elemento_despesa'),
            dados.get('uo'),
            1,  # ENVIADO_GOOGLE_FORMS (marcado como enviado, pois será aberto no navegador)
            datetime.now()  # DATA_ENVIO
        )
        
        cursor.execute(sql_insert, valores)
        id_oc = cursor.lastrowid
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'success': True,
            'message': 'Ordem Cronológica salva com sucesso!',
            'id_oc': id_oc
        })
        
    except Exception as e:
        print(f"Erro ao salvar Ordem Cronológica: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })



@app.route('/enviar-form', methods=['POST'])
def enviar_para_google_form():
    """
    Salva dados da Ordem Cronológica e envia para o Google Forms
    """
    try:
        dados = request.json
        
        # ========================================
        # 1. SALVAR NO BANCO DE DADOS
        # ========================================
        cursor = mysql.connection.cursor()
        
        sql_insert = """
            INSERT INTO ORDEM_CRONOLOGICA (
                NU_PROCESSO, DOC_COBRANCA, NM_FORNECEDOR, CPF_CNPJ,
                VL_CREDITO, DT_RECEBIMENTO, DT_PAGAMENTO, NU_CONTRATO,
                CAT_CONTRATO, VL_CONTRATO, TIPO_CONTRATO, GESTOR_CONTRATO,
                COMARCA_GESTOR, UNIDADE_GESTOR, NU_EMPENHO, ELEMENTO_DESPESA,
                UO, ENVIADO_GOOGLE_FORMS, DATA_ENVIO
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """
        
        valores = (
            dados.get('nu_processo'),
            dados.get('doc_cobranca'),
            dados.get('nm_fornecedor'),
            dados.get('cpf_cnpj'),
            float(dados.get('vl_credito', 0)),
            dados.get('dt_recebimento'),
            dados.get('dt_pagamento'),
            dados.get('nu_contrato'),
            dados.get('cat_contrato'),
            float(dados.get('vl_contrato', 0)),
            dados.get('tipo_contrato'),
            dados.get('gestor_contrato'),
            dados.get('comarca_gestor'),
            dados.get('unidade_gestor'),
            dados.get('nu_empenho'),
            dados.get('elemento_despesa'),
            dados.get('uo'),
            0,  # ENVIADO_GOOGLE_FORMS (False inicialmente)
            None  # DATA_ENVIO (será atualizado após envio bem-sucedido)
        )
        
        cursor.execute(sql_insert, valores)
        id_oc = cursor.lastrowid
        mysql.connection.commit()
        
        # ========================================
        # 2. ENVIAR PARA O GOOGLE FORMS
        # ========================================
        import requests
        
        form_url = "https://docs.google.com/forms/d/e/1FAIpQLSdA--nxkR3GGB0RdW6FVjSPjkgdmhnXvRckJkc-tDKT2kSV7A/formResponse"
        
        # Mapeamento para os campos do Google Form
        form_data = {
            'entry.28426199': dados.get('nu_processo'),           # Nº Processo
            'entry.848082802': dados.get('doc_cobranca'),         # Nº Documento Cobrança
            'entry.2129481572': dados.get('nm_fornecedor'),       # Nome Fornecedor
            'entry.1980182805': dados.get('cpf_cnpj'),            # CPF/CNPJ
            'entry.627188067': f"R$ {float(dados.get('vl_credito', 0)):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),  # Valor Crédito
            'entry.374609461': dados.get('dt_recebimento'),       # Data Recebimento
            'entry.630584389': dados.get('dt_pagamento'),         # Data Pagamento
            'entry.1174998288': dados.get('nu_contrato'),         # Nº Contrato
            'entry.1759342712': dados.get('cat_contrato'),        # Categoria do Contrato
            'entry.535843603': f"R$ {float(dados.get('vl_contrato', 0)):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'),  # Valor do Contrato
            'entry.1364276952': dados.get('tipo_contrato'),       # Tipo de Contrato
            'entry.784298439': dados.get('gestor_contrato'),      # Gestor(a) do Contrato
            'entry.1453029380': dados.get('comarca_gestor'),      # Comarca de Locação
            'entry.1058830341': dados.get('unidade_gestor'),      # Unidade de Lotação
            'entry.1966894067': dados.get('nu_empenho'),          # Nº Empenho
            'entry.1797655161': dados.get('elemento_despesa'),    # Elemento de Despesa
            'entry.1401767695': dados.get('uo')                   # Unidade Orçamentária
        }
        
        # Enviar requisição POST para o Google Forms
        response = requests.post(form_url, data=form_data)
        
        # ========================================
        # 3. ATUALIZAR STATUS DE ENVIO
        # ========================================
        if response.status_code == 200:
            sql_update = """
                UPDATE ORDEM_CRONOLOGICA 
                SET ENVIADO_GOOGLE_FORMS = 1, DATA_ENVIO = NOW()
                WHERE ID_OC = %s
            """
            cursor.execute(sql_update, (id_oc,))
            mysql.connection.commit()
            
            cursor.close()
            
            return jsonify({
                'success': True,
                'message': 'Ordem Cronológica salva e enviada com sucesso!',
                'id_oc': id_oc
            })
        else:
            cursor.close()
            return jsonify({
                'success': False,
                'error': f'Erro ao enviar para o Google Forms. Status: {response.status_code}'
            })
        
    except Exception as e:
        print(f"Erro ao enviar para Google Forms: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/contrato/<int:id_contrato>', methods=['GET'])
def api_buscar_contrato(id_contrato):
    """
    Busca dados completos do contrato incluindo fornecedor
    """
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        sql = """
            SELECT 
                c.ID_CONTROLE,
                c.ID_FORNECEDOR,
                c.EXERCICIO,
                c.PROCESSO,
                c.ATA_PREGAO,
                c.CONTRATO,
                c.SETOR_GESTOR,
                c.NOME_GESTOR,
                c.CIDADE,
                c.VL_CONTRATO,
                c.ELEMENTO_DESPESA,
                c.UO,
                c.CAT_CONTRATO,
                c.TIPO_CONTRATO,
                f.NM_FORNECEDOR,
                f.CNPJ_FORNECEDOR
            FROM CONTROLE_PASSAGENS_AEREAS c
            INNER JOIN CAD_FORNECEDOR f ON c.ID_FORNECEDOR = f.ID_FORNECEDOR
            WHERE c.ID_CONTROLE = %s
        """
        
        cursor.execute(sql, (id_contrato,))
        contrato = cursor.fetchone()
        cursor.close()
        
        if contrato:
            return jsonify({
                'success': True,
                'data': contrato
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Contrato não encontrado'
            })
        
    except Exception as e:
        print(f"Erro ao buscar contrato: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })


###################################

# Decorator para verificar permissão de acesso
def verificar_permissao(url_pagina, nivel_minimo='L'):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'usuario_id' not in session:
                return redirect(url_for('login'))
                     
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT p.NIVEL_ACESSO
                FROM CAD_USUARIO u
                INNER JOIN CAD_PERMISSAO p ON u.ID_GRUPO = p.ID_GRUPO
                INNER JOIN CAD_PAGINA pg ON p.ID_PAGINA = pg.ID_PAGINA
                WHERE u.ID_USUARIO = %s AND pg.URL_PAGINA = %s
            """, (session['usuario_id'], url_pagina))
                     
            permissao = cur.fetchone()
            cur.close()
                     
            # Sem permissão ou acesso negado - redireciona para página de erro
            if not permissao or permissao[0] == 'N':
                return render_template('acesso_negado.html', 
                                     mensagem='Você não tem permissão para acessar esta página.')
                     
            # Se requer edição e tem apenas leitura - permite acesso mas em modo leitura
            if nivel_minimo == 'E' and permissao[0] == 'L':
                session['nivel_acesso_atual'] = 'L'
            else:
                session['nivel_acesso_atual'] = permissao[0]
                     
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/index2')
@login_required
def index2():
    return render_template('index2.html')

@app.route('/login')
def login():
    if 'usuario_logado' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/autenticar', methods=['POST'])
def autenticar():
    login = request.form['login']
    senha = request.form['senha']
    
    senha_criptografada = criptografar(senha)
    
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT u.ID_USUARIO, u.NM_USUARIO, u.ID_GRUPO, g.NM_GRUPO
        FROM CAD_USUARIO u
        LEFT JOIN CAD_GRUPO g ON u.ID_GRUPO = g.ID_GRUPO
        WHERE u.US_LOGIN = %s 
        AND u.SENHA = %s 
        AND u.FL_STATUS = 'A'
    """, (login, senha_criptografada))
    
    usuario = cur.fetchone()
    cur.close()
    
    if usuario:
        session['usuario_logado'] = True
        session['usuario_id'] = usuario[0]
        session['usuario_login'] = login
        session['usuario_nome'] = usuario[1]
        session['usuario_grupo_id'] = usuario[2]
        session['usuario_grupo_nome'] = usuario[3]
        
        return jsonify({
            'sucesso': True,
            'usuario_id': usuario[0],
            'usuario_login': login,
            'usuario_nome': usuario[1],
            'usuario_grupo': usuario[3]
        })
    else:
        return jsonify({'sucesso': False, 'mensagem': 'Credenciais inválidas'})

# Rota para a página de cadastro de usuários
@app.route('/cadastro_usuarios')
@login_required
@verificar_permissao('/cadastro_usuarios', 'E')
def cadastro_usuarios():
    return render_template('cadastro_usuarios.html')

# Rota para listar usuários
@app.route('/api/usuarios', methods=['GET'])
@login_required
def listar_usuarios():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT u.ID_USUARIO, u.US_LOGIN, u.NM_USUARIO, 
               g.NM_GRUPO, u.FL_STATUS
        FROM CAD_USUARIO u
        LEFT JOIN CAD_GRUPO g ON u.ID_GRUPO = g.ID_GRUPO
        ORDER BY u.NM_USUARIO
    """)
    
    usuarios = []
    for row in cur.fetchall():
        usuarios.append({
            'id': row[0],
            'login': row[1],
            'nome': row[2],
            'grupo': row[3],
            'status': row[4]
        })
    
    cur.close()
    return jsonify(usuarios)

# Rota para listar grupos
@app.route('/api/grupos', methods=['GET'])
@login_required
def listar_grupos():
    cur = mysql.connection.cursor()
    cur.execute("SELECT ID_GRUPO, NM_GRUPO FROM CAD_GRUPO WHERE FL_STATUS = 'A' ORDER BY NM_GRUPO")
    
    grupos = []
    for row in cur.fetchall():
        grupos.append({
            'id': row[0],
            'nome': row[1]
        })
    
    cur.close()
    return jsonify(grupos)

# Rota para criar usuário
@app.route('/api/usuarios', methods=['POST'])
@login_required
def criar_usuario():
    dados = request.json
    
    login = dados.get('login')
    nome = dados.get('nome')
    grupo_id = dados.get('grupo_id')
    senha = dados.get('senha')
    status = dados.get('status', 'A')
    
    if not all([login, nome, grupo_id, senha]):
        return jsonify({'erro': 'Dados incompletos'}), 400
    
    senha_criptografada = criptografar(senha)
    
    cur = mysql.connection.cursor()
    
    # Verifica se o login já existe
    cur.execute("SELECT ID_USUARIO FROM CAD_USUARIO WHERE US_LOGIN = %s", (login,))
    if cur.fetchone():
        cur.close()
        return jsonify({'erro': 'Login já existe'}), 400
    
    cur.execute("""
        INSERT INTO CAD_USUARIO (US_LOGIN, NM_USUARIO, ID_GRUPO, SENHA, FL_STATUS)
        VALUES (%s, %s, %s, %s, %s)
    """, (login, nome, grupo_id, senha_criptografada, status))
    
    mysql.connection.commit()
    usuario_id = cur.lastrowid
    cur.close()
    
    return jsonify({'sucesso': True, 'id': usuario_id}), 201

# Rota para atualizar usuário
@app.route('/api/usuarios/<int:id>', methods=['PUT'])
@login_required
def atualizar_usuario(id):
    dados = request.json
    
    nome = dados.get('nome')
    grupo_id = dados.get('grupo_id')
    senha = dados.get('senha')
    status = dados.get('status')
    
    if not all([nome, grupo_id, status]):
        return jsonify({'erro': 'Dados incompletos'}), 400
    
    cur = mysql.connection.cursor()
    
    if senha:
        senha_criptografada = criptografar(senha)
        cur.execute("""
            UPDATE CAD_USUARIO 
            SET NM_USUARIO = %s, ID_GRUPO = %s, SENHA = %s, FL_STATUS = %s
            WHERE ID_USUARIO = %s
        """, (nome, grupo_id, senha_criptografada, status, id))
    else:
        cur.execute("""
            UPDATE CAD_USUARIO 
            SET NM_USUARIO = %s, ID_GRUPO = %s, FL_STATUS = %s
            WHERE ID_USUARIO = %s
        """, (nome, grupo_id, status, id))
    
    mysql.connection.commit()
    cur.close()
    
    return jsonify({'sucesso': True})

# Rota para deletar usuário
@app.route('/api/usuarios/<int:id>', methods=['DELETE'])
@login_required
def deletar_usuario(id):
    # Não permite deletar o próprio usuário
    if id == session.get('usuario_id'):
        return jsonify({'erro': 'Não é possível deletar o próprio usuário'}), 400
    
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM CAD_USUARIO WHERE ID_USUARIO = %s", (id,))
    mysql.connection.commit()
    cur.close()
    
    return jsonify({'sucesso': True})

@app.route('/logout')
def logout():
    session.clear()
    # Se a requisição vier via AJAX, retornar JSON
    if request.headers.get('Content-Type') == 'application/json':
        return jsonify({'success': True})
    return redirect(url_for('login'))

# ============================================================
# ROTA PARA ALTERAR SENHA DO USUÁRIO
# ============================================================
@app.route('/api/alterar-senha', methods=['POST'])
@login_required
def alterar_senha():
    """
    Altera a senha do usuário logado
    Requer autenticação e validação da senha atual
    """
    cur = None
    try:
        # Log para debug
        print("=== INICIANDO ALTERAÇÃO DE SENHA ===")
        
        # Obter dados do request
        dados = request.get_json()
        print(f"Dados recebidos: {dados is not None}")
        
        if not dados:
            print("❌ Nenhum dado recebido")
            return jsonify({
                'sucesso': False,
                'mensagem': 'Nenhum dado foi enviado.'
            }), 400
        
        senha_atual = dados.get('senha_atual')
        senha_nova = dados.get('senha_nova')
        
        print(f"Senha atual recebida: {senha_atual is not None}")
        print(f"Senha nova recebida: {senha_nova is not None}")
        
        # Validações básicas
        if not senha_atual or not senha_nova:
            print("❌ Campos obrigatórios ausentes")
            return jsonify({
                'sucesso': False,
                'mensagem': 'Todos os campos são obrigatórios.'
            }), 400
        
        if len(senha_nova) < 6:
            print("❌ Senha muito curta")
            return jsonify({
                'sucesso': False,
                'mensagem': 'A nova senha deve ter no mínimo 6 caracteres.'
            }), 400
        
        # Obter ID do usuário logado
        usuario_id = session.get('usuario_id')
        usuario_login = session.get('usuario_login')
        
        print(f"Usuário ID: {usuario_id}")
        print(f"Usuário Login: {usuario_login}")
        
        if not usuario_id:
            print("❌ Usuário não autenticado")
            return jsonify({
                'sucesso': False,
                'mensagem': 'Usuário não autenticado.'
            }), 401
        
        # Criptografar senha atual para verificação
        senha_atual_criptografada = criptografar(senha_atual)
        print(f"Senha atual criptografada: {senha_atual_criptografada[:10]}...")
        
        # Verificar se a senha atual está correta
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT ID_USUARIO, SENHA 
            FROM CAD_USUARIO 
            WHERE ID_USUARIO = %s 
            AND FL_STATUS = 'A'
        """, (usuario_id,))
        
        usuario = cur.fetchone()
        
        if not usuario:
            print("❌ Usuário não encontrado ou inativo")
            cur.close()
            return jsonify({
                'sucesso': False,
                'mensagem': 'Usuário não encontrado.'
            }), 400
        
        senha_banco = usuario[1]
        print(f"Senha do banco: {senha_banco[:10]}...")
        print(f"Senhas coincidem: {senha_atual_criptografada == senha_banco}")
        
        if senha_atual_criptografada != senha_banco:
            print("❌ Senha atual incorreta")
            cur.close()
            return jsonify({
                'sucesso': False,
                'mensagem': 'Senha atual incorreta.'
            }), 400
        
        # Criptografar nova senha
        senha_nova_criptografada = criptografar(senha_nova)
        print(f"Nova senha criptografada: {senha_nova_criptografada[:10]}...")
        
        # Atualizar senha no banco
        cur.execute("""
            UPDATE CAD_USUARIO 
            SET SENHA = %s 
            WHERE ID_USUARIO = %s
        """, (senha_nova_criptografada, usuario_id))
        
        mysql.connection.commit()
        print(f"✅ Senha atualizada com sucesso para usuário ID: {usuario_id}")
        
        cur.close()
        
        return jsonify({
            'sucesso': True,
            'mensagem': 'Senha alterada com sucesso!'
        })
        
    except Exception as e:
        print(f"❌ Erro ao alterar senha: {str(e)}")
        import traceback
        traceback.print_exc()
        
        if cur:
            try:
                mysql.connection.rollback()
            except:
                pass
        
        return jsonify({
            'sucesso': False,
            'mensagem': f'Erro ao processar solicitação: {str(e)}'
        }), 500
    
    finally:
        if cur:
            try:
                cur.close()
            except:
                pass


# Rota para listar todas as páginas
@app.route('/api/paginas', methods=['GET'])
@login_required
def listar_paginas():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT ID_PAGINA, NM_PAGINA, DS_PAGINA, URL_PAGINA, FL_STATUS
        FROM CAD_PAGINA 
        WHERE FL_STATUS = 'A'
        ORDER BY NM_PAGINA
    """)
    
    paginas = []
    for row in cur.fetchall():
        paginas.append({
            'id': row[0],
            'nome': row[1],
            'descricao': row[2],
            'url': row[3],
            'status': row[4]
        })
    
    cur.close()
    return jsonify(paginas)

@app.route('/api/paginas/<int:id>', methods=['GET'])
@login_required
def obter_pagina(id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT ID_PAGINA, NM_PAGINA, DS_PAGINA, URL_PAGINA, FL_STATUS
        FROM CAD_PAGINA
        WHERE ID_PAGINA = %s
    """, (id,))
    
    row = cur.fetchone()
    cur.close()
    
    if row:
        return jsonify({
            'id': row[0],
            'nome': row[1],
            'descricao': row[2],
            'url': row[3],
            'status': row[4]
        })
    else:
        return jsonify({'erro': 'Página não encontrada'}), 404


@app.route('/api/paginas', methods=['POST'])
@login_required
def criar_pagina():
    dados = request.get_json()
    
    nome = dados.get('nome')
    descricao = dados.get('descricao', '')
    url = dados.get('url')
    status = dados.get('status', 'A')
    
    if not nome or not url:
        return jsonify({'erro': 'Nome e URL são obrigatórios'}), 400
    
    cur = mysql.connection.cursor()
    
    try:
        # Insere a página
        cur.execute("""
            INSERT INTO CAD_PAGINA (NM_PAGINA, DS_PAGINA, URL_PAGINA, FL_STATUS)
            VALUES (%s, %s, %s, %s)
        """, (nome, descricao, url, status))
        
        id_pagina = cur.lastrowid
        
        # Busca todos os grupos
        cur.execute("SELECT ID_GRUPO FROM CAD_GRUPO WHERE FL_STATUS = 'A'")
        grupos = cur.fetchall()
        
        # Insere permissões para todos os grupos
        for grupo in grupos:
            id_grupo = grupo[0]
            # Administrador (ID_GRUPO=1) recebe 'E', outros recebem 'N'
            nivel_acesso = 'E' if id_grupo == 1 else 'N'
            
            cur.execute("""
                INSERT INTO CAD_PERMISSAO (ID_GRUPO, ID_PAGINA, NIVEL_ACESSO)
                VALUES (%s, %s, %s)
            """, (id_grupo, id_pagina, nivel_acesso))
        
        mysql.connection.commit()
        
        return jsonify({
            'mensagem': 'Página criada com sucesso',
            'id': id_pagina
        }), 201
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'erro': str(e)}), 500
    finally:
        cur.close()


@app.route('/api/paginas/<int:id>', methods=['PUT'])
@login_required
def atualizar_pagina(id):
    dados = request.get_json()
    
    nome = dados.get('nome')
    descricao = dados.get('descricao', '')
    url = dados.get('url')
    status = dados.get('status')
    
    if not nome or not url:
        return jsonify({'erro': 'Nome e URL são obrigatórios'}), 400
    
    cur = mysql.connection.cursor()
    
    try:
        cur.execute("""
            UPDATE CAD_PAGINA
            SET NM_PAGINA = %s, DS_PAGINA = %s, URL_PAGINA = %s, FL_STATUS = %s
            WHERE ID_PAGINA = %s
        """, (nome, descricao, url, status, id))
        
        mysql.connection.commit()
        
        if cur.rowcount == 0:
            return jsonify({'erro': 'Página não encontrada'}), 404
        
        return jsonify({'mensagem': 'Página atualizada com sucesso'})
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'erro': str(e)}), 500
    finally:
        cur.close()


@app.route('/api/paginas/<int:id>', methods=['DELETE'])
@login_required
def deletar_pagina(id):
    cur = mysql.connection.cursor()
    
    try:
        # Deleta as permissões relacionadas
        cur.execute("DELETE FROM CAD_PERMISSAO WHERE ID_PAGINA = %s", (id,))
        
        # Deleta a página
        cur.execute("DELETE FROM CAD_PAGINA WHERE ID_PAGINA = %s", (id,))
        
        mysql.connection.commit()
        
        if cur.rowcount == 0:
            return jsonify({'erro': 'Página não encontrada'}), 404
        
        return jsonify({'mensagem': 'Página excluída com sucesso'})
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'erro': str(e)}), 500
    finally:
        cur.close()


# Rota para buscar permissões de um grupo específico
@app.route('/api/permissoes/grupo/<int:grupo_id>', methods=['GET'])
@login_required
def buscar_permissoes_grupo(grupo_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT p.ID_PAGINA, pg.NM_PAGINA, 
               COALESCE(p.NIVEL_ACESSO, 'N') as NIVEL_ACESSO
        FROM CAD_PAGINA pg
        LEFT JOIN CAD_PERMISSAO p ON pg.ID_PAGINA = p.ID_PAGINA AND p.ID_GRUPO = %s
        WHERE pg.FL_STATUS = 'A'
        ORDER BY pg.NM_PAGINA
    """, (grupo_id,))
    
    permissoes = []
    for row in cur.fetchall():
        permissoes.append({
            'id_pagina': row[0],
            'nome_pagina': row[1],
            'nivel_acesso': row[2]
        })
    
    cur.close()
    return jsonify(permissoes)

# Rota para atualizar permissões de um grupo
@app.route('/api/permissoes/grupo/<int:grupo_id>', methods=['PUT'])
@login_required
def atualizar_permissoes_grupo(grupo_id):
    dados = request.json
    permissoes = dados.get('permissoes', [])
    
    if not permissoes:
        return jsonify({'erro': 'Nenhuma permissão informada'}), 400
    
    cur = mysql.connection.cursor()
    
    try:
        # Para cada permissão, verifica se existe e atualiza ou insere
        for perm in permissoes:
            id_pagina = perm['id_pagina']
            nivel_acesso = perm['nivel_acesso']
            
            # Verifica se a permissão já existe
            cur.execute("""
                SELECT ID_PERMISSAO 
                FROM CAD_PERMISSAO 
                WHERE ID_GRUPO = %s AND ID_PAGINA = %s
            """, (grupo_id, id_pagina))
            
            existe = cur.fetchone()
            
            if existe:
                # Atualiza
                cur.execute("""
                    UPDATE CAD_PERMISSAO 
                    SET NIVEL_ACESSO = %s
                    WHERE ID_GRUPO = %s AND ID_PAGINA = %s
                """, (nivel_acesso, grupo_id, id_pagina))
            else:
                # Insere
                cur.execute("""
                    INSERT INTO CAD_PERMISSAO (ID_GRUPO, ID_PAGINA, NIVEL_ACESSO)
                    VALUES (%s, %s, %s)
                """, (grupo_id, id_pagina, nivel_acesso))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({'sucesso': True})
    
    except Exception as e:
        mysql.connection.rollback()
        cur.close()
        return jsonify({'erro': str(e)}), 500


@app.route('/nova_vistoria')
def nova_vistoria():
    # Busca motoristas e veículos do banco de dados
    cur = mysql.connection.cursor()
    cur.execute("SELECT ID_MOTORISTA, NM_MOTORISTA FROM CAD_MOTORISTA WHERE ID_MOTORISTA <> 0 AND ATIVO = 'S' ORDER BY NM_MOTORISTA")
    motoristas = cur.fetchall()
    cur.execute("SELECT ID_VEICULO, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO FROM CAD_VEICULOS WHERE ATIVO = 'S' AND FL_ATENDIMENTO = 'S' ORDER BY DS_MODELO, NU_PLACA")
    veiculos = cur.fetchall()
    cur.close()
    
    return render_template('nova_vistoria.html', motoristas=motoristas, veiculos=veiculos, tipo='SAIDA')

@app.route('/nova_vistoria2')
def nova_vistoria2():
    # Busca motoristas e veículos do banco de dados
    cur = mysql.connection.cursor()
    cur.execute("SELECT ID_MOTORISTA, NM_MOTORISTA FROM CAD_MOTORISTA WHERE ID_MOTORISTA <> 0 AND ATIVO = 'S' ORDER BY NM_MOTORISTA")
    motoristas = cur.fetchall()
    cur.execute("SELECT ID_VEICULO, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO FROM CAD_VEICULOS WHERE ATIVO = 'S' AND FL_ATENDIMENTO = 'S' ORDER BY DS_MODELO, NU_PLACA")
    veiculos = cur.fetchall()
    cur.close()
    
    return render_template('nova_vistoria2.html', motoristas=motoristas, veiculos=veiculos, tipo='INICIAL')

@app.route('/confirma_vistoria/<int:id>')
def confirma_vistoria(id):
    
    session['vistoria_id'] = id
    print(f" ID VISTORIA: {id}")
    cur = mysql.connection.cursor()
    
    # Buscar detalhes da vistoria
    cur.execute("""
        SELECT v.IDVISTORIA, v.IDMOTORISTA, m.NM_MOTORISTA as MOTORISTA, v.IDVEICULO, 
               CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO, v.DATA, v.TIPO, v.STATUS, 
               v.COMBUSTIVEL, v.HODOMETRO, ve.DS_MODELO, v.VISTORIA_SAIDA_ID,  
               v.ASS_USUARIO, v.ASS_MOTORISTA, v.OBS, v.DATA_SAIDA, v.DATA_RETORNO, v.NU_SEI
        FROM VISTORIAS v
        JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.TIPO = 'INICIAL' AND v.IDVISTORIA = %s
    """, (id,))
    vistoria = cur.fetchone()
    if vistoria:
        return render_template(
            'confirma_vistoria.html',
            vistoria_id=vistoria[0],
            motorista_id=vistoria[1],
            motorista_nome=vistoria[2],
            veiculo_id=vistoria[3],
            veiculo_placa=vistoria[4],
            combustivel=vistoria[8],
            hodometro=vistoria[9],
	    data_saida=vistoria[15],
	    data_retorno=vistoria[16],
	    nu_sei=vistoria[17],
            tipo='INICIAL'
        )
    else:
        return redirect(url_for('ver_vistoria2', id=id))
       
@app.route('/nova_vistoria_devolucao/<int:vistoria_saida_id>')
def nova_vistoria_devolucao(vistoria_saida_id):
    # Buscar informações da vistoria de saida
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT v.IDVISTORIA, v.IDMOTORISTA, v.IDVEICULO, m.NM_MOTORISTA, 
	ve.NU_PLACA, v.COMBUSTIVEL, v.DATA_SAIDA, v.DATA_RETORNO, v.NU_SEI
        FROM VISTORIAS v
        JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.IDVISTORIA = %s AND v.TIPO = 'SAIDA'
    """, (vistoria_saida_id,))
    vistoria_saida = cur.fetchone()
    cur.close()
    
    if not vistoria_saida:
        flash('Vistoria de saida não encontrada!', 'danger')
        return redirect(url_for('vistorias'))
    
    return render_template(
        'nova_vistoria.html', 
        motorista_id=vistoria_saida[1],
        motorista_nome=vistoria_saida[3],
        veiculo_id=vistoria_saida[2],
        veiculo_placa=vistoria_saida[4],
        vistoria_saida_id=vistoria_saida_id,
	data_saida=vistoria_saida[6],
	data_retorno=vistoria_saida[7],
	nu_sei=vistoria_saida[8],
        tipo='DEVOLUCAO'
    )

@app.route('/salvar_vistoria', methods=['POST'])
def salvar_vistoria():
    # ============================================
    # DEBUG CRÍTICO - NÃO REMOVA AINDA
    # ============================================
    import sys
    print("=" * 80, file=sys.stderr)
    print("🔍 INICIANDO SALVAMENTO DE VISTORIA", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    
    print("\n📋 FORM DATA:", file=sys.stderr)
    for key, value in request.form.items():
        print(f"  {key}: {value}", file=sys.stderr)
    
    print("\n📁 FILES:", file=sys.stderr)
    for key in request.files.keys():
        files = request.files.getlist(key)
        print(f"  {key}: {len(files)} arquivo(s)", file=sys.stderr)
    
    print("=" * 80, file=sys.stderr)
    # ============================================
    
    try:
        # Obter dados do formulário
        motorista_nao_cadastrado_str = request.form.get('motorista_nao_cadastrado', 'false')
        motorista_nao_cadastrado = motorista_nao_cadastrado_str.lower() == 'true'
        
        print(f"✅ Checkpoint 1: motorista_nao_cadastrado = {motorista_nao_cadastrado}", file=sys.stderr)
        
        # Se motorista não cadastrado, pegar o nome digitado, senão pegar o ID
        if motorista_nao_cadastrado:
            id_motorista = 0
            nc_motorista = request.form.get('nc_motorista', '').strip()
            
            print(f"✅ Checkpoint 2: Motorista NC = '{nc_motorista}'", file=sys.stderr)
            
            if not nc_motorista:
                print(f"❌ ERRO: Nome do motorista NC vazio!", file=sys.stderr)
                flash('Por favor, informe o nome do motorista não cadastrado.', 'danger')
                return redirect(request.referrer)
        else:
            id_motorista = request.form.get('id_motorista')
            nc_motorista = None
            
            print(f"✅ Checkpoint 3: Motorista cadastrado ID = {id_motorista}", file=sys.stderr)
            
            if not id_motorista:
                print(f"❌ ERRO: ID do motorista vazio!", file=sys.stderr)
                flash('Por favor, selecione um motorista.', 'danger')
                return redirect(request.referrer)
        
        print(f"✅ Checkpoint 4: Validação de motorista OK", file=sys.stderr)
        
        # Continua com o resto do código...
        id_veiculo = request.form['id_veiculo']
        tipo = request.form['tipo']
        
        print(f"✅ Checkpoint 5: Pegando outros dados...", file=sys.stderr)

        vistoria_saida_id = request.form.get('vistoria_saida_id')
        combustivel = request.form['combustivel']
        hodometro = request.form['hodometro']
        obs = request.form['observacoes']
        data_saida = request.form['dataSaida']
        # Obter data_retorno apenas se estiver presente no formulário
        data_retorno = request.form.get('dataRetorno', None)
        nu_sei = request.form.get('numSei', '')  # Tornando campo SEI opcional
        
        print(f"✅ Checkpoint 6: Dados básicos OK", file=sys.stderr)
        
        # Obter o nome do usuário da sessão
        usuario_nome = session.get('usuario_nome', 'Sistema')
        # Obter as assinaturas
        assinatura_usuario_data = request.form.get('assinatura_usuario')
        assinatura_motorista_data = request.form.get('assinatura_motorista')
        
        print(f"✅ Checkpoint 7: Assinaturas obtidas", file=sys.stderr)
        
        # Processar as assinaturas de base64 para binário, se existirem
        assinatura_usuario_bin = None
        assinatura_motorista_bin = None
        
        if assinatura_usuario_data and ',' in assinatura_usuario_data:
            assinatura_usuario_data = assinatura_usuario_data.split(',')[1]
            assinatura_usuario_bin = base64.b64decode(assinatura_usuario_data)
        
        if assinatura_motorista_data and ',' in assinatura_motorista_data:
            assinatura_motorista_data = assinatura_motorista_data.split(',')[1]
            assinatura_motorista_bin = base64.b64decode(assinatura_motorista_data)
        
        print(f"✅ Checkpoint 8: Assinaturas processadas", file=sys.stderr)
        
        # Criar uma nova vistoria
        cur = mysql.connection.cursor()
        
        # Capturar o último ID antes da inserção
        cur.execute("SELECT MAX(IDVISTORIA) FROM VISTORIAS")
        ultimo_id = cur.fetchone()[0] or 0
        data_e_hora_atual = datetime.now()
        fuso_horario = timezone('America/Manaus')
        data_hora = data_e_hora_atual.astimezone(fuso_horario)
        
        print(f"✅ Checkpoint 9: Preparando INSERT...", file=sys.stderr)
    
        if tipo == 'SAIDA':
            # Para vistorias de SAIDA, definir status como EM_TRANSITO
            print(f"✅ Checkpoint 10: Inserindo SAIDA - ID_MOTORISTA={id_motorista}, NC_MOTORISTA={nc_motorista}", file=sys.stderr)
            cur.execute(
                """INSERT INTO VISTORIAS 
                   (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, COMBUSTIVEL, HODOMETRO, 
                   ASS_USUARIO, ASS_MOTORISTA, OBS, USUARIO, DATA_SAIDA, NU_SEI, NC_MOTORISTA) 
                   VALUES (%s, %s, %s, %s, 'EM_TRANSITO', %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_motorista, id_veiculo, data_hora, tipo, combustivel, hodometro, 
                 assinatura_usuario_bin, assinatura_motorista_bin, obs, usuario_nome, data_saida, nu_sei, nc_motorista)
            )
        else:  # DEVOLUCAO
            # Para vistorias de DEVOLUCAO, definir status como FINALIZADA
            print(f"✅ Checkpoint 10: Inserindo DEVOLUCAO - ID_MOTORISTA={id_motorista}, NC_MOTORISTA={nc_motorista}", file=sys.stderr)
            cur.execute(
                """INSERT INTO VISTORIAS 
                   (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, VISTORIA_SAIDA_ID, COMBUSTIVEL, 
                   HODOMETRO, ASS_USUARIO, ASS_MOTORISTA, OBS, USUARIO, DATA_SAIDA, DATA_RETORNO, NU_SEI, NC_MOTORISTA) 
                   VALUES (%s, %s, %s, %s, 'FINALIZADA', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_motorista, id_veiculo, data_hora, tipo, vistoria_saida_id, combustivel, hodometro, 
                 assinatura_usuario_bin, assinatura_motorista_bin, obs, usuario_nome, data_saida, data_retorno, nu_sei, nc_motorista)
            )
            # Atualizar status da vistoria de saida para finalizada
            cur.execute(
                "UPDATE VISTORIAS SET STATUS = 'FINALIZADA' WHERE IDVISTORIA = %s",
                (vistoria_saida_id,)
            )
        
        print(f"✅ Checkpoint 11: INSERT executado com sucesso", file=sys.stderr)
            
        # Realizar o commit para garantir que a vistoria foi salva
        mysql.connection.commit()
        
        print(f"✅ Checkpoint 12: COMMIT realizado", file=sys.stderr)
        
        # Buscar o ID da vistoria recém-inserida procurando o ID maior que o último ID conhecido
        cur.execute("SELECT IDVISTORIA FROM VISTORIAS WHERE IDVISTORIA > %s ORDER BY IDVISTORIA ASC LIMIT 1", (ultimo_id,))
        result = cur.fetchone()
        
        if not result:
            raise Exception("Não foi possível recuperar o ID da vistoria criada")
        
        id_vistoria = result[0]
        print(f"✅ Checkpoint 13: ID da vistoria recuperado: {id_vistoria} (último ID: {ultimo_id})", file=sys.stderr)
        
        # Debug: Verificar recebimento das fotos
        fotos = request.files.getlist('fotos[]')
        detalhamentos = request.form.getlist('detalhamentos[]')
        
        print(f"✅ Checkpoint 14: Tipo={tipo}, Fotos={len(fotos)}, Detalhamentos={len(detalhamentos)}", file=sys.stderr)
        
        # Processar todas as fotos de uma vez
        for i, foto in enumerate(fotos):
            if foto:  # Apenas verificar se o objeto de arquivo existe
                try:
                    # Ler o conteúdo binário da imagem
                    foto_data = foto.read()
                    
                    detalhamento = detalhamentos[i] if i < len(detalhamentos) else ""
                    
                    # Inserir explicitamente o conteúdo binário da imagem com o ID da vistoria confirmado
                    print(f"  📸 Inserindo foto {i+1}/{len(fotos)} para vistoria {id_vistoria}", file=sys.stderr)
                    
                    # VERIFICAÇÃO EXTRA: Confirmar que a vistoria existe antes de inserir
                    cur.execute("SELECT 1 FROM VISTORIAS WHERE IDVISTORIA = %s", (id_vistoria,))
                    if not cur.fetchone():
                        print(f"  ❌ ALERTA: Vistoria com ID {id_vistoria} não encontrada!", file=sys.stderr)
                        continue
                    
                    cur.execute(
                        "INSERT INTO VISTORIA_ITENS (IDVISTORIA, FOTO) VALUES (%s, %s)",
                        (id_vistoria, foto_data)
                    )
                    mysql.connection.commit()
                    
                    # VERIFICAÇÃO FINAL: Confirmar que o item foi inserido corretamente
                    cur.execute("SELECT IDVISTORIA FROM VISTORIA_ITENS WHERE ID = LAST_INSERT_ID()")
                    item_result = cur.fetchone()
                    if item_result and item_result[0] != id_vistoria:
                        print(f"  ❌ ALERTA: Item inserido com IDVISTORIA incorreto: {item_result[0]} != {id_vistoria}", file=sys.stderr)
                        
                except Exception as e:
                    print(f"  ❌ Erro ao processar foto {i}: {str(e)}", file=sys.stderr)
        
        cur.close()
        
        print(f"✅ Checkpoint 15: Tudo OK! Redirecionando...", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        
        flash('Vistoria salva com sucesso!', 'success')
        return redirect(url_for('index'))
    
    except Exception as e:
        print(f"❌❌❌ ERRO CRÍTICO: {str(e)}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        flash(f'Erro ao salvar vistoria: {str(e)}', 'danger')
        return redirect(url_for('nova_vistoria'))
        
@app.route('/ultima_vistoria')
def ultima_vistoria():
    try:
        # Recuperar o ID da última vistoria inserida
        cur = mysql.connection.cursor()
        cur.execute("SELECT MAX(IDVISTORIA) FROM VISTORIAS")
        result = cur.fetchone()
        cur.close()
        
        if not result or not result[0]:
            return jsonify({
                'success': False,
                'message': 'Nenhuma vistoria encontrada'
            }), 404
            
        id_vistoria = result[0]
        
        return jsonify({
            'success': True,
            'id_vistoria': id_vistoria
        })
    
    except Exception as e:
        flash(f'Erro ao salvar vistoria: {str(e)}', 'danger')
        return redirect(url_for('nova_vistoria'))

@app.route('/salvar_vistoria2', methods=['POST'])
def salvar_vistoria2():
    try:
        # Obter dados do formulário
        id_motorista = request.form['id_motorista']
        id_veiculo = request.form['id_veiculo']
        tipo = request.form['tipo']
        vistoria_saida_id = request.form.get('vistoria_saida_id')
        combustivel = request.form['combustivel']
        hodometro = request.form['hodometro']
        obs = request.form['observacoes']
        data_saida = request.form['dataSaida']
        data_retorno = request.form['dataRetorno']
        nu_sei = request.form['numSei']      
        
        print(f"Data Saida { data_saida }")
        print(f"Data Retorno { data_retorno }")
        print(f"Sei { nu_sei }")
        
        
        # Obter o nome do usuário da sessão
        usuario_nome = session.get('usuario_nome')
        
        # Criar uma nova vistoria
        cur = mysql.connection.cursor()
        
        # Capturar o último ID antes da inserção
        cur.execute("SELECT MAX(IDVISTORIA) FROM VISTORIAS")
        ultimo_id = cur.fetchone()[0] or 0
        data_e_hora_atual = datetime.now()
        fuso_horario = timezone('America/Manaus')
        data_hora = data_e_hora_atual.astimezone(fuso_horario)
    
        cur.execute(
            """INSERT INTO VISTORIAS 
                (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, COMBUSTIVEL, 
                HODOMETRO, OBS, USUARIO, DATA_SAIDA, DATA_RETORNO, NU_SEI) 
                VALUES (%s, %s, %s, %s, 'EM_TRANSITO', %s, %s, %s, %s, %s, %s, %s)""",
            (id_motorista, id_veiculo, data_hora, tipo, combustivel, 
             hodometro, obs, usuario_nome, data_saida, data_retorno, nu_sei)
        )
            
        # Realizar o commit para garantir que a vistoria foi salva
        mysql.connection.commit()
        
        # Buscar o ID da vistoria recém-inserida procurando o ID maior que o último ID conhecido
        cur.execute("SELECT IDVISTORIA FROM VISTORIAS WHERE IDVISTORIA > %s ORDER BY IDVISTORIA ASC LIMIT 1", (ultimo_id,))
        result = cur.fetchone()
        
        if not result:
            raise Exception("Não foi possível recuperar o ID da vistoria criada")
        
        id_vistoria = result[0]
        print(f"ID da vistoria recuperado: {id_vistoria} (último ID antes da inserção: {ultimo_id})")
        
        cur.close()
        
        # Retornar um JSON com o ID da vistoria
        return jsonify({'success': True, 'id_vistoria': id_vistoria})
        
    except Exception as e:
        print(f"ERRO CRÍTICO: {str(e)}")
        flash(f'Erro ao salvar vistoria: {str(e)}', 'danger')
        return redirect(url_for('nova_vistoria'))

@app.route('/salvar_vistoria3', methods=['POST'])
def salvar_vistoria3():
    try:
        id_vistoria = session.get('vistoria_id')
        print(f" ID VISTORIA: {id_vistoria}")
        if id_vistoria is None:
            # Caso o id não esteja na sessão
            return "ID da vistoria não encontrado na sessão", 400
        
        # Obter dados do formulário
        tipo = 'CONFIRMACAO' 
        combustivel = request.form['combustivel']
        hodometro = request.form['hodometro']
        obs = request.form['observacoes']
        
        # Obter as assinaturas
        assinatura_motorista_data = request.form.get('assinatura_motorista')
        
        # Processar as assinaturas de base64 para binário, se existirem
        assinatura_motorista_bin = None
                    
        if assinatura_motorista_data and ',' in assinatura_motorista_data:
            assinatura_motorista_data = assinatura_motorista_data.split(',')[1]
            try:
                assinatura_motorista_bin = base64.b64decode(assinatura_motorista_data)
            except Exception as e:
                print(f"Erro ao decodificar assinatura: {str(e)}")
        
        # Iniciar transação
        cur = mysql.connection.cursor()
        
        try:
            data_e_hora_atual = datetime.now()
            fuso_horario = timezone('America/Manaus')
            data_hora = data_e_hora_atual.astimezone(fuso_horario)
            
            print(f"Dados para UPDATE: data={data_hora}, combustivel={combustivel}, hodometro={hodometro}, obs={obs}, tipo={tipo}, id={id_vistoria}")
            
            # Use o valor de tipo do formulário em vez de definir estaticamente
            cur.execute(
                """UPDATE VISTORIAS SET 
                    DATA = %s,
                    COMBUSTIVEL = %s, 
                    HODOMETRO = %s,
                    ASS_MOTORISTA = %s,
                    OBS = %s,
                    TIPO = %s
                    WHERE IDVISTORIA = %s 
                    """,
                (data_hora, combustivel, hodometro, assinatura_motorista_bin, obs, tipo, id_vistoria)
            )
            
            # Debug: Verificar se o update afetou alguma linha
            rows_affected = cur.rowcount
            print(f"Linhas afetadas pelo UPDATE: {rows_affected}")
            
            # Processar todas as fotos
            fotos = request.files.getlist('fotos[]')
            detalhamentos = request.form.getlist('detalhamentos[]')
            
            print(f"Tipo de vistoria: {tipo}")
            print(f"Número de fotos recebidas: {len(fotos)}")
            print(f"Número de detalhamentos recebidos: {len(detalhamentos)}")
            
            
            # Processar todas as fotos de uma vez
            for i, foto in enumerate(fotos):
                if foto and foto.filename:  # Verificar se o arquivo existe e tem um nome
                    try:
                        # Ler o conteúdo binário da imagem
                        foto_data = foto.read()
                        
                        # Obter o detalhamento correspondente
                        detalhamento = detalhamentos[i] if i < len(detalhamentos) else ""
                        
                        # Inserir a foto e o detalhamento
                        print(f"Inserindo item {i} para vistoria {id_vistoria}")
                        
                        # Adicione o campo detalhamento à sua query se ele existir na tabela
                        cur.execute(
                            "INSERT INTO VISTORIA_ITENS (IDVISTORIA, FOTO, DETALHAMENTO) VALUES (%s, %s, %s)",
                            (id_vistoria, foto_data, detalhamento)
                        )
                        
                        # Verificar se o item foi inserido
                        item_id = cur.lastrowid
                        print(f"Item inserido com ID: {item_id}")
                        
                    except Exception as e:
                        print(f"Erro ao processar foto {i}: {str(e)}")
                        # Não fazemos rollback aqui para continuar processando outras fotos
            
            # Commit após todas as operações
            mysql.connection.commit()
            flash('Vistoria salva com sucesso!', 'success')
            
        except Exception as e:
            # Se houver erro, fazemos rollback
            mysql.connection.rollback()
            raise e
            
        finally:
            cur.close()
            
        return redirect(url_for('index'))
    
    except Exception as e:
        print(f"ERRO CRÍTICO: {str(e)}")
        flash(f'Erro ao salvar vistoria: {str(e)}', 'danger')
        return redirect(url_for('nova_vistoria'))
    
@app.route('/salvar_foto', methods=['POST'])
def salvar_foto():
    try:
        data = request.json
        image_data = data['image_data']
        
        # Remover o prefixo da string base64
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Decodificar a imagem base64 para binário
        image_binary = base64.b64decode(image_data)
        
        # Gerar um ID temporário para a imagem
        temp_id = str(uuid.uuid4())
        
        # Armazenar temporariamente na sessão ou devolver para o cliente
        return jsonify({'success': True, 'temp_id': temp_id, 'image_data': image_data})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/vistorias')
def listar_vistorias():
    cur = mysql.connection.cursor()
    
    # Buscar vistorias em trânsito (Saidas não finalizadas)
    cur.execute("""
        SELECT v.IDVISTORIA, 
        CASE WHEN v.IDMOTORISTA='0'
        THEN CONCAT('* ',v.NC_MOTORISTA)
        ELSE m.NM_MOTORISTA END as MOTORISTA, 
        CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
        v.DATA, v.TIPO, v.STATUS, v.OBS 
        FROM VISTORIAS v
        JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.STATUS = 'EM_TRANSITO' AND v.TIPO = 'SAIDA'
        ORDER BY v.DATA DESC
    """)
    vistorias_em_transito = cur.fetchall()
    # Buscar vistorias em Pendentes
    cur.execute("""
        SELECT v.IDVISTORIA, 
        CASE WHEN v.IDMOTORISTA='0'
        THEN CONCAT('* ',v.NC_MOTORISTA)
        ELSE m.NM_MOTORISTA END as MOTORISTA,
        CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO,
        v.DATA, v.TIPO, v.STATUS, v.OBS 
        FROM VISTORIAS v
        JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.TIPO IN ('INICIAL', 'CONFIRMACAO')
        ORDER BY v.DATA DESC
    """)
    vistorias_pendentes = cur.fetchall()
    # Buscar vistorias finalizadas (Saidas com devolução ou devoluções)
    cur.execute("""
        SELECT v.IDVISTORIA, 
        CASE WHEN v.IDMOTORISTA='0'
        THEN CONCAT('* ',v.NC_MOTORISTA)
        ELSE m.NM_MOTORISTA END as MOTORISTA,		
        CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
        v.DATA, v.TIPO, v.STATUS, v.OBS, 
        COALESCE((SELECT IDVISTORIA FROM VISTORIAS WHERE VISTORIA_SAIDA_ID = v.IDVISTORIA),'') AS ID_DEVOLUCAO
        FROM VISTORIAS v
        JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.TIPO = 'SAIDA' 
        AND v.STATUS = 'FINALIZADA'
        ORDER BY v.DATA DESC
    """)
    vistorias_finalizadas = cur.fetchall()
    
    cur.close()
    
    return render_template(
        'vistorias.html', 
        vistorias_em_transito=vistorias_em_transito,
        vistorias_pendentes=vistorias_pendentes,
        vistorias_finalizadas=vistorias_finalizadas
    )

@app.route('/vistoria/<int:id>')
def ver_vistoria(id):
    try:
        cur = mysql.connection.cursor()
        # Buscar detalhes da vistoria
        cur.execute("""
            SELECT v.IDVISTORIA, 
                   CASE WHEN v.IDMOTORISTA='0'
                   THEN CONCAT('* ',v.NC_MOTORISTA)
                   ELSE m.NM_MOTORISTA END as MOTORISTA, 
                   CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
                   v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO, v.VISTORIA_SAIDA_ID, 
                   v.ASS_USUARIO, v.ASS_MOTORISTA, v.HODOMETRO, v.OBS, v.USUARIO, 
                   v.DATA_SAIDA, v.DATA_RETORNO, v.NU_SEI, v.NC_MOTORISTA
            FROM VISTORIAS v
            LEFT JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
            JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
            WHERE v.IDVISTORIA = %s
        """, (id,))
        vistoria = cur.fetchone()
       
        # Verificações seguras para evitar erros
        vistoria_saida = None
        vistoria_saida_itens = []
        vistoria_devolucao = None
        vistoria_devolucao_itens = []
        itens = []
        
        if vistoria:
            # Se for uma vistoria de devolução, buscar também a vistoria de saida
            if vistoria[4] == 'DEVOLUCAO' and vistoria[8]:
                cur.execute("""
                    SELECT v.IDVISTORIA, 
                           CASE WHEN v.IDMOTORISTA='0'
                           THEN CONCAT('* ',v.NC_MOTORISTA)
                           ELSE m.NM_MOTORISTA END as MOTORISTA,
                           CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
                           v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO,
                           v.VISTORIA_SAIDA_ID, v.ASS_USUARIO, v.ASS_MOTORISTA, v.HODOMETRO, 
                           v.OBS, v.USUARIO, v.NC_MOTORISTA
                    FROM VISTORIAS v
                    LEFT JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
                    JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
                    WHERE v.IDVISTORIA = %s
                """, (vistoria[8],))
                vistoria_saida = cur.fetchone()
                
                # Buscar fotos da vistoria de saída
                cur.execute("""
                    SELECT ID, DETALHAMENTO
                    FROM VISTORIA_ITENS
                    WHERE IDVISTORIA = %s
                """, (vistoria[8],))
                vistoria_saida_itens = cur.fetchall() or []
            
            # Se for uma vistoria de saida, buscar se já existe uma vistoria de devolução
            if vistoria[4] == 'SAIDA':
                cur.execute("""
                    SELECT v.IDVISTORIA, 
                           CASE WHEN v.IDMOTORISTA='0'
                           THEN CONCAT('* ',v.NC_MOTORISTA)
                           ELSE m.NM_MOTORISTA END as MOTORISTA,
                           CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
                           v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO,
                           v.VISTORIA_SAIDA_ID, v.ASS_USUARIO, v.ASS_MOTORISTA, v.HODOMETRO, 
                           v.OBS, v.USUARIO, v.NC_MOTORISTA
                    FROM VISTORIAS v
                    LEFT JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
                    JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
                    WHERE v.VISTORIA_SAIDA_ID = %s
                """, (id,))
                vistoria_devolucao = cur.fetchone()
                
                # Buscar fotos da vistoria de devolução
                if vistoria_devolucao:
                    cur.execute("""
                        SELECT ID, DETALHAMENTO
                        FROM VISTORIA_ITENS
                        WHERE IDVISTORIA = %s
                    """, (vistoria_devolucao[0],))
                    vistoria_devolucao_itens = cur.fetchall() or []
            
            # Buscar fotos desta vistoria atual
            cur.execute("""
                SELECT ID, DETALHAMENTO
                FROM VISTORIA_ITENS
                WHERE IDVISTORIA = %s
            """, (id,))
            itens_raw = cur.fetchall() or []
            
            # Converter para dicionários para uso no template
            itens = [{'id': item[0], 'detalhamento': item[1]} for item in itens_raw]
            vistoria_saida_itens = [{'id': item[0], 'detalhamento': item[1]} for item in vistoria_saida_itens]
            vistoria_devolucao_itens = [{'id': item[0], 'detalhamento': item[1]} for item in vistoria_devolucao_itens]
        
        cur.close()
        
        return render_template(
            'ver_vistoria.html', 
            vistoria=vistoria, 
            itens=itens,
            vistoria_saida=vistoria_saida,
            vistoria_saida_itens=vistoria_saida_itens,
            vistoria_devolucao=vistoria_devolucao,
            vistoria_devolucao_itens=vistoria_devolucao_itens
        )
    except Exception as e:
        # Adiciona log do erro para depuração
        app.logger.error(f"Erro na rota ver_vistoria: {str(e)}")
        
        # Encerra o cursor se ainda estiver aberto
        if 'cur' in locals() and cur:
            cur.close()
        
        # Retorna uma página de erro amigável
        return render_template('error.html', error_message=str(e)), 500
    
@app.route('/vistoria_finaliza/<int:id>')
def vistoria_finaliza(id):
    cur = mysql.connection.cursor()
    
    # Buscar detalhes da vistoria
    cur.execute("""
        SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO, 
               v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO,
               v.VISTORIA_SAIDA_ID, v.ASS_USUARIO, v.ASS_MOTORISTA, v.HODOMETRO, v.OBS
        FROM VISTORIAS v
        JOIN CAD_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN CAD_VEICULOS ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.IDVISTORIA = %s
    """, (id,))
    vistoria = cur.fetchone()
        
    # Buscar fotos e detalhamentos da vistoria
    cur.execute("""
        SELECT ID, DETALHAMENTO
        FROM VISTORIA_ITENS
        WHERE IDVISTORIA = %s
    """, (id,))
    itens_raw = cur.fetchall()
    
    # Converter para dicionários para uso no template
    itens = []
    for item in itens_raw:
        itens.append({
            'id': item[0],
            'detalhamento': item[1]
        })
    
    cur.close()
    
    return render_template(
        'vistoria_finaliza.html', 
        vistoria=vistoria, 
        itens=itens
    )

@app.route('/salvar_assinatura', methods=['POST'])
def salvar_assinatura():
    try:
        # Verifica se os dados foram recebidos
        if not request.is_json:
            return jsonify({'success': False, 'message': 'Dados inválidos. Esperado JSON.'}), 400
            
        data = request.json
        
        # Verifica se os campos necessários estão presentes
        if 'vistoria_id' not in data or 'assinatura' not in data:
            return jsonify({'success': False, 'message': 'Campos obrigatórios não fornecidos'}), 400
            
        vistoria_id = data.get('vistoria_id')
        assinatura_base64 = data.get('assinatura')
        
        # Valida o ID da vistoria
        if not vistoria_id or not str(vistoria_id).isdigit():
            return jsonify({'success': False, 'message': 'ID de vistoria inválido'}), 400
        
        # Valida o formato da assinatura base64
        if not assinatura_base64 or not assinatura_base64.startswith('data:image'):
            return jsonify({'success': False, 'message': 'Formato de assinatura inválido'}), 400
        
        try:
            # Remove o prefixo da string base64
            img_data = assinatura_base64.split(',')[1]
            # Converte a string base64 para dados binários
            img_binary = base64.b64decode(img_data)
        except Exception as e:
            app.logger.error(f"Erro ao processar imagem: {str(e)}")
            return jsonify({'success': False, 'message': 'Erro ao processar imagem'}), 400
        
        try:
            # Conecta ao banco de dados
            cur = mysql.connection.cursor()
            cur.execute("UPDATE VISTORIAS SET TIPO = 'SAIDA', ASS_USUARIO = %s WHERE IDVISTORIA = %s", 
                        (img_binary, vistoria_id))
                        
            # Fecha a conexão
            cur.close()
            
            # Verifica se alguma linha foi afetada
            if cur.rowcount == 0:
                return jsonify({'success': False, 'message': f'Vistoria ID {vistoria_id} não encontrada'}), 404
                
            # Commit das alterações
            mysql.connection.commit()
            
            # Fecha a conexão
            cur.close()
            
            return jsonify({'success': True, 'message': 'Assinatura salva com sucesso'})
            
        except Exception as db_error:
            app.logger.error(f"Erro de banco de dados: {str(db_error)}")
            return jsonify({'success': False, 'message': f'Erro de banco de dados: {str(db_error)}'}), 500
            
    except Exception as e:
        app.logger.error(f"Erro interno: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_foto/<int:item_id>')
def get_foto(item_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT FOTO FROM VISTORIA_ITENS WHERE ID = %s", (item_id,))
    foto = cur.fetchone()
    cur.close()
    
    if foto and foto[0]:
        return send_file(
            BytesIO(foto[0]),
            mimetype='image/jpeg',
            as_attachment=False,
            download_name=f'foto_{item_id}.jpg'
        )
    
    return 'Imagem não encontrada', 404

@app.route('/get_assinatura/<tipo>/<int:vistoria_id>')
def get_assinatura(tipo, vistoria_id):
    cur = mysql.connection.cursor()
    
    if tipo == 'usuario':
        cur.execute("SELECT ASS_USUARIO FROM VISTORIAS WHERE IDVISTORIA = %s", (vistoria_id,))
    else:  # tipo == 'motorista'
        cur.execute("SELECT ASS_MOTORISTA FROM VISTORIAS WHERE IDVISTORIA = %s", (vistoria_id,))
    
    resultado = cur.fetchone()
    cur.close()
    
    if not resultado or not resultado[0]:
        return "Sem assinatura", 404
    
    assinatura = resultado[0]
    
    return send_file(
        BytesIO(assinatura),
        mimetype='image/png',  # ou 'image/jpeg' dependendo do formato da assinatura
        as_attachment=False,
        download_name=f'assinatura_{tipo}_{vistoria_id}.png'  # nome do arquivo ao baixar
    )
    
def criptografar(texto):
    key = '123456'
    resultado = ''
    
    for i in range(len(texto)):
        # Aplica XOR entre o caractere do texto e o caractere correspondente da chave
        c = ord(key[i % len(key)]) ^ ord(texto[i])
        # Converte para hexadecimal e garante que tenha 2 dígitos
        resultado += f'{c:02x}'
    
    return resultado
def descriptografar(texto):
    key = '123456'
    resultado = ''
    
    # Processa cada par de caracteres hexadecimais
    for i in range(0, len(texto) // 2):
        # Converte o par de caracteres hexadecimais para um valor inteiro
        try:
            c = int(texto[i*2:i*2+2], 16)
        except ValueError:
            # Se não for possível converter, usa espaço como fallback (como no Delphi)
            c = ord(' ')
        
        # Aplica XOR novamente para reverter a criptografia
        c = ord(key[i % len(key)]) ^ c
        resultado += chr(c)
    
    return resultado

@app.route('/motoristas')
@login_required
def pagina_motoristas():
    return render_template('motoristas.html')

@app.route('/api/setores')
@login_required
def listar_setores():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT SIGLA_SETOR FROM CAD_SETORES ORDER BY SIGLA_SETOR")
        setores = [{'sigla': row[0]} for row in cursor.fetchall()]
        cursor.close()
        return jsonify(setores)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

############################################
# ROTAS DO CADASTRO DE MOTORISTAS
############################################

@app.route('/api/motoristas')
@login_required
def listar_motoristas():
    cursor = None
    try:
        nome = request.args.get('nome', '')
        cursor = mysql.connection.cursor()
        
        if nome:
            app.logger.info(" ::::  Executando consulta de motorista com parametro ::::  ")
            query = """
            SELECT 
                ID_MOTORISTA, CAD_MOTORISTA,
                CASE WHEN ATIVO='S' THEN NM_MOTORISTA 
                ELSE CONCAT(NM_MOTORISTA,' (INATIVO)') END AS MOTORISTA,
                ORDEM_LISTA AS TIPO_CADASTRO, SIGLA_SETOR,
                FILE_PDF IS NOT NULL AS FILE_PDF, ATIVO
            FROM CAD_MOTORISTA 
            WHERE ID_MOTORISTA > 0
            AND CONCAT(CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, SIGLA_SETOR) LIKE %s 
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query, (f'%{nome}%',))
        else:
            app.logger.info(" ::::  Listando todos os motorista ::::  ")
            query = """
            SELECT 
                ID_MOTORISTA, CAD_MOTORISTA, 
                CASE WHEN ATIVO='S' THEN NM_MOTORISTA 
                ELSE CONCAT(NM_MOTORISTA,' (INATIVO)') END AS MOTORISTA, 
                ORDEM_LISTA AS TIPO_CADASTRO, SIGLA_SETOR,
                FILE_PDF IS NOT NULL AS FILE_PDF, ATIVO
            FROM CAD_MOTORISTA
            WHERE ID_MOTORISTA > 0
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query)
            
        columns = ['id_motorista', 'cad_motorista', 'nm_motorista', 'tipo_cadastro', 'sigla_setor', 'file_pdf', 'ativo', 'dt_inicio', 'dt_fim']
        motoristas = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        return jsonify(motoristas)
        
    except Exception as e:
        app.logger.error(f"Erro ao listar motoristas: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'erro': str(e)}), 500
        
    finally:
        if cursor:
            cursor.close()
			
# API atualizada para detalhe do motorista incluindo ID_FORNECEDOR
@app.route('/api/motoristas/<int:id_motorista>')
@login_required
def detalhe_motorista(id_motorista):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT 
            ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, ORDEM_LISTA, 
            SIGLA_SETOR, CAT_CNH, DT_VALIDADE_CNH, ULTIMA_ATUALIZACAO, 
            NU_TELEFONE, OBS_MOTORISTA, ATIVO, NOME_ARQUIVO, EMAIL,
            ID_FORNECEDOR
        FROM CAD_MOTORISTA 
        WHERE ID_MOTORISTA = %s
        """
        cursor.execute(query, (id_motorista,))
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            motorista = {
                'id_motorista': result[0],
                'cad_motorista': result[1],
                'nm_motorista': result[2],
                'tipo_cadastro': result[3],
                'sigla_setor': result[4],
                'cat_cnh': result[5],
                'dt_validade_cnh': result[6],
                'ultima_atualizacao': result[7],
                'nu_telefone': result[8],
                'obs_motorista': result[9],
                'ativo': result[10],
                'nome_arquivo': result[11],
                'email': result[12],
                'id_fornecedor': result[13]
            }
            return jsonify(motorista)
        else:
            return jsonify({'erro': 'Motorista não encontrado'}), 404
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

# API para listar fornecedores
@app.route('/api/motorista/fornecedores')
@login_required
def motorista_listar_fornecedores():
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT ID_FORNECEDOR, NM_FORNECEDOR 
        FROM CAD_FORNECEDOR
        ORDER BY NM_FORNECEDOR
        """
        cursor.execute(query)
        columns = ['id_fornecedor', 'nm_fornecedor']
        fornecedores = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        return jsonify(fornecedores)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
		
@app.route('/api/motoristas/cadastrar', methods=['POST'])
@login_required
def cadastrar_motorista():
    tipo_cad = {
        1: 'Administrativo',
        2: 'Motorista Desembargador',
        3: 'Motorista Atendimento',
        4: 'Cadastro de Condutores',
        5: 'Terceirizado'    
    }
    try:
        cursor = mysql.connection.cursor()
        
        # Get last ID and increment
        cursor.execute("SELECT COALESCE(MAX(ID_MOTORISTA), 0) + 1 FROM CAD_MOTORISTA")
        novo_id = cursor.fetchone()[0]
        
        # Form data
        cad_motorista = request.form.get('cad_motorista')
        nm_motorista = request.form.get('nm_motorista')
        tipo_cadastro = int(request.form.get('tipo_cadastro'))
        sigla_setor = request.form.get('sigla_setor')
        cat_cnh = request.form.get('cat_cnh')
        dt_validade_cnh = request.form.get('dt_validade_cnh')
        ultima_atualizacao = request.form.get('ultima_atualizacao')
        nu_telefone = request.form.get('nu_telefone')
        obs_motorista = request.form.get('obs_motorista', '')
        email = request.form.get('email', '')
        id_fornecedor = request.form.get('id_fornecedor', None)  # CORRIGIDO - indentação
        
        # Converter id_fornecedor para None se estiver vazio
        if id_fornecedor == '' or id_fornecedor == 'null':
            id_fornecedor = None
        
        tipo_cadastro_desc = tipo_cad[tipo_cadastro]
        
        # File handling
        file_pdf = request.files.get('file_pdf')
        nome_arquivo = None
        file_blob = None
        if file_pdf:
            nome_arquivo = file_pdf.filename
            file_blob = file_pdf.read()
        
        # Get current timestamp in Manaus timezone
        manaus_tz = timezone('America/Manaus')
        dt_transacao = datetime.now(manaus_tz).strftime('%d/%m/%Y %H:%M:%S')
                
        # Insert query
        query = """
        INSERT INTO CAD_MOTORISTA (
            ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, SIGLA_SETOR, CAT_CNH, 
            DT_VALIDADE_CNH, ULTIMA_ATUALIZACAO, NU_TELEFONE, OBS_MOTORISTA, ATIVO, USUARIO, 
            DT_TRANSACAO, FILE_PDF, NOME_ARQUIVO, ORDEM_LISTA, EMAIL, ID_FORNECEDOR
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'S', %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            novo_id, cad_motorista, nm_motorista, tipo_cadastro_desc, 
            sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
            nu_telefone, obs_motorista, session.get('usuario_id'), 
            dt_transacao, file_blob, nome_arquivo, tipo_cadastro, email,
            id_fornecedor
        ))

        manaus_tz = timezone('America/Manaus')
        data_atual = datetime.now(manaus_tz).date()

        cursor.execute('''
            INSERT INTO CAD_MOTORISTA_PERIODOS 
            (ID_MOTORISTA, DT_INICIO, DT_FIM, USUARIO, DT_TRANSACAO)
            VALUES (%s, %s, NULL, %s, NOW())
        ''', (novo_id, data_atual, session.get('usuario_id')))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'sucesso': True, 'id_motorista': novo_id})
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao cadastrar motorista: {str(e)}")  # Debug
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500

@app.route('/api/motoristas/atualizar', methods=['POST'])
@login_required
def atualizar_motorista():
    tipo_cad = {
        1: 'Administrativo',
        2: 'Motorista Desembargador',
        3: 'Motorista Atendimento',
        4: 'Cadastro de Condutores',
        5: 'Terceirizado'
    }
    try:
        cursor = mysql.connection.cursor()
        
        # Form data
        id_motorista = request.form.get('id_motorista')
        cad_motorista = request.form.get('cad_motorista')
        nm_motorista = request.form.get('nm_motorista')
        tipo_cadastro = int(request.form.get('tipo_cadastro'))
        sigla_setor = request.form.get('sigla_setor')
        cat_cnh = request.form.get('cat_cnh')
        dt_validade_cnh = request.form.get('dt_validade_cnh')
        ultima_atualizacao = request.form.get('ultima_atualizacao')
        nu_telefone = request.form.get('nu_telefone')
        obs_motorista = request.form.get('obs_motorista', '')
        email = request.form.get('email', '')
        ativo = 'S' if request.form.get('ativo') == 'on' else 'N'
        id_fornecedor = request.form.get('id_fornecedor', None)  # CORRIGIDO - indentação
        
        # Converter id_fornecedor para None se estiver vazio
        if id_fornecedor == '' or id_fornecedor == 'null':
            id_fornecedor = None
        
        tipo_cadastro_desc = tipo_cad[tipo_cadastro]
        
        # File 
        file_pdf = request.files.get('file_pdf')
        nome_arquivo = None
        file_blob = None
        
        # Check if new file is uploaded
        if file_pdf:
            nome_arquivo = file_pdf.filename
            file_blob = file_pdf.read()
        
        # Get current timestamp in Manaus timezone
        manaus_tz = timezone('America/Manaus')
        dt_transacao = datetime.now(manaus_tz).strftime('%d/%m/%Y %H:%M:%S')
                
        # Update query 
        if file_pdf:
            # Update with file
            query = """
            UPDATE CAD_MOTORISTA 
            SET CAD_MOTORISTA = %s, NM_MOTORISTA = %s, TIPO_CADASTRO = %s, 
                SIGLA_SETOR = %s, CAT_CNH = %s, DT_VALIDADE_CNH = %s, 
                ULTIMA_ATUALIZACAO = %s, NU_TELEFONE = %s, OBS_MOTORISTA = %s, 
                ATIVO = %s, USUARIO = %s, 
                FILE_PDF = %s, NOME_ARQUIVO = %s, ORDEM_LISTA = %s, EMAIL = %s,
                ID_FORNECEDOR = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                file_blob, nome_arquivo, tipo_cadastro, email,
                id_fornecedor, id_motorista
            ))
        else:
            # Update without changing file
            query = """
            UPDATE CAD_MOTORISTA 
            SET CAD_MOTORISTA = %s, NM_MOTORISTA = %s, TIPO_CADASTRO = %s, 
                SIGLA_SETOR = %s, CAT_CNH = %s, DT_VALIDADE_CNH = %s, 
                ULTIMA_ATUALIZACAO = %s, NU_TELEFONE = %s, OBS_MOTORISTA = %s, 
                ATIVO = %s, USUARIO = %s, ORDEM_LISTA = %s, EMAIL = %s,
                ID_FORNECEDOR = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                tipo_cadastro, email, id_fornecedor, id_motorista
            ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'sucesso': True, 'id_motorista': id_motorista})
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao atualizar motorista: {str(e)}")  # Debug
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500

@app.route('/api/motoristas/download_cnh/<int:id_motorista>')
@login_required
def download_cnh(id_motorista):
    try:
        cursor = mysql.connection.cursor()
        query = "SELECT FILE_PDF, NOME_ARQUIVO FROM CAD_MOTORISTA WHERE ID_MOTORISTA = %s"
        cursor.execute(query, (id_motorista,))
        result = cursor.fetchone()
        cursor.close()
        if result and result[0]:
            return send_file(
                BytesIO(result[0]),
                mimetype='application/pdf',
                as_attachment=True,  # Mantém o download
                download_name=result[1]
            )
        else:
            return "Arquivo não encontrado", 404
    except Exception as e:
        return str(e), 500

# NOVA ROTA PARA VISUALIZAÇÃO (adicione esta)
@app.route('/api/motoristas/visualizar_cnh/<int:id_motorista>')
@login_required
def visualizar_cnh(id_motorista):
    try:
        cursor = mysql.connection.cursor()
        query = "SELECT FILE_PDF, NOME_ARQUIVO FROM CAD_MOTORISTA WHERE ID_MOTORISTA = %s"
        cursor.execute(query, (id_motorista,))
        result = cursor.fetchone()
        cursor.close()
        if result and result[0]:
            return send_file(
                BytesIO(result[0]),
                mimetype='application/pdf',
                as_attachment=False,  # AQUI: False para visualizar
                download_name=result[1]
            )
        else:
            return "Arquivo não encontrado", 404
    except Exception as e:
        return str(e), 500

# ========== ROTA: Listar períodos de um motorista ==========
@app.route('/api/motoristas/<int:id_motorista>/periodos')
@login_required
def listar_periodos_motorista(id_motorista):
    """
    Lista todos os períodos de vínculo de um motorista
    """
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT 
            ID_PERIODO,
            ID_MOTORISTA,
            DATE_FORMAT(DT_INICIO, '%%d/%%m/%%Y') as DT_INICIO,
            DATE_FORMAT(DT_FIM, '%%d/%%m/%%Y') as DT_FIM,
            USUARIO,
            DATE_FORMAT(DT_TRANSACAO, '%%d/%%m/%%Y %%H:%%i:%%s') as DT_TRANSACAO,
            CASE WHEN DT_FIM IS NULL THEN 'S' ELSE 'N' END as PERIODO_ATIVO
        FROM CAD_MOTORISTA_PERIODOS
        WHERE ID_MOTORISTA = %s
        ORDER BY DT_INICIO DESC
        """
        cursor.execute(query, (id_motorista,))
        
        columns = ['id_periodo', 'id_motorista', 'dt_inicio', 'dt_fim', 'usuario', 'dt_transacao', 'periodo_ativo']
        periodos = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        cursor.close()
        return jsonify({'success': True, 'periodos': periodos})
        
    except Exception as e:
        app.logger.error(f"Erro ao listar períodos: {str(e)}")
        return jsonify({'success': False, 'erro': str(e)}), 500


# ========== ROTA: Adicionar novo período ==========
@app.route('/api/motoristas/<int:id_motorista>/periodos/adicionar', methods=['POST'])
@login_required
def adicionar_periodo_motorista(id_motorista):
    """
    Adiciona um novo período de vínculo para um motorista
    Validações:
    - Apenas 1 período ativo (DT_FIM NULL) por motorista
    - Sem sobreposição de datas
    - DT_FIM >= DT_INICIO
    """
    try:
        data = request.get_json()
        dt_inicio = data.get('dt_inicio')  # Formato: DD/MM/YYYY
        dt_fim = data.get('dt_fim')  # Formato: DD/MM/YYYY ou null
        
        if not dt_inicio:
            return jsonify({'success': False, 'erro': 'Data de início é obrigatória'}), 400
        
        # Converter DT_INICIO de DD/MM/YYYY para YYYY-MM-DD
        dia, mes, ano = dt_inicio.split('/')
        dt_inicio_db = f"{ano}-{mes}-{dia}"
        
        # Converter DT_FIM se fornecida
        dt_fim_db = None
        if dt_fim:
            dia, mes, ano = dt_fim.split('/')
            dt_fim_db = f"{ano}-{mes}-{dia}"
        
        cursor = mysql.connection.cursor()
        
        # Inserir novo período (as validações estão no trigger)
        query = """
        INSERT INTO CAD_MOTORISTA_PERIODOS 
        (ID_MOTORISTA, DT_INICIO, DT_FIM, USUARIO, DT_TRANSACAO)
        VALUES (%s, %s, %s, %s, NOW())
        """
        
        cursor.execute(query, (
            id_motorista, 
            dt_inicio_db, 
            dt_fim_db, 
            session.get('usuario_id')
        ))
        
        id_periodo = cursor.lastrowid
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'success': True, 
            'id_periodo': id_periodo,
            'mensagem': 'Período adicionado com sucesso!'
        })
        
    except Exception as e:
        mysql.connection.rollback()
        erro_msg = str(e)
        
        # Mensagens amigáveis para erros do trigger
        if 'Data fim deve ser maior' in erro_msg:
            erro_msg = 'A data fim deve ser maior ou igual à data início'
        elif 'período ativo' in erro_msg:
            erro_msg = 'Já existe um período ativo para este motorista. Encerre o período anterior antes de criar um novo.'
        elif 'sobrepõe' in erro_msg:
            erro_msg = 'Este período se sobrepõe a um período existente. Verifique as datas.'
        
        app.logger.error(f"Erro ao adicionar período: {erro_msg}")
        return jsonify({'success': False, 'erro': erro_msg}), 400


# ========== ROTA: Atualizar período existente ==========
@app.route('/api/motoristas/<int:id_motorista>/periodos/<int:id_periodo>/atualizar', methods=['POST'])
@login_required
def atualizar_periodo_motorista(id_motorista, id_periodo):
    """
    Atualiza um período existente
    Principais usos:
    - Encerrar período ativo (adicionar DT_FIM)
    - Corrigir datas
    """
    try:
        data = request.get_json()
        dt_inicio = data.get('dt_inicio')  # Formato: DD/MM/YYYY
        dt_fim = data.get('dt_fim')  # Formato: DD/MM/YYYY ou null
        
        if not dt_inicio:
            return jsonify({'success': False, 'erro': 'Data de início é obrigatória'}), 400
        
        # Converter DT_INICIO de DD/MM/YYYY para YYYY-MM-DD
        dia, mes, ano = dt_inicio.split('/')
        dt_inicio_db = f"{ano}-{mes}-{dia}"
        
        # Converter DT_FIM se fornecida
        dt_fim_db = None
        if dt_fim:
            dia, mes, ano = dt_fim.split('/')
            dt_fim_db = f"{ano}-{mes}-{dia}"
        
        cursor = mysql.connection.cursor()
        
        # Atualizar período (as validações estão no trigger)
        query = """
        UPDATE CAD_MOTORISTA_PERIODOS 
        SET DT_INICIO = %s, 
            DT_FIM = %s,
            USUARIO = %s,
            DT_TRANSACAO = NOW()
        WHERE ID_PERIODO = %s 
        AND ID_MOTORISTA = %s
        """
        
        cursor.execute(query, (
            dt_inicio_db, 
            dt_fim_db, 
            session.get('usuario_id'),
            id_periodo,
            id_motorista
        ))
        
        if cursor.rowcount == 0:
            mysql.connection.rollback()
            cursor.close()
            return jsonify({'success': False, 'erro': 'Período não encontrado'}), 404
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'success': True,
            'mensagem': 'Período atualizado com sucesso!'
        })
        
    except Exception as e:
        mysql.connection.rollback()
        erro_msg = str(e)
        
        # Mensagens amigáveis para erros do trigger
        if 'Data fim deve ser maior' in erro_msg:
            erro_msg = 'A data fim deve ser maior ou igual à data início'
        elif 'período ativo' in erro_msg:
            erro_msg = 'Já existe um período ativo para este motorista. Encerre o período anterior antes de criar um novo.'
        elif 'sobrepõe' in erro_msg:
            erro_msg = 'Este período se sobrepõe a um período existente. Verifique as datas.'
        
        app.logger.error(f"Erro ao atualizar período: {erro_msg}")
        return jsonify({'success': False, 'erro': erro_msg}), 400


# ========== ROTA: Excluir período ==========
@app.route('/api/motoristas/<int:id_motorista>/periodos/<int:id_periodo>/excluir', methods=['DELETE'])
@login_required
def excluir_periodo_motorista(id_motorista, id_periodo):
    """
    Exclui um período de vínculo
    """
    try:
        cursor = mysql.connection.cursor()
        
        query = """
        DELETE FROM CAD_MOTORISTA_PERIODOS 
        WHERE ID_PERIODO = %s 
        AND ID_MOTORISTA = %s
        """
        
        cursor.execute(query, (id_periodo, id_motorista))
        
        if cursor.rowcount == 0:
            mysql.connection.rollback()
            cursor.close()
            return jsonify({'success': False, 'erro': 'Período não encontrado'}), 404
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'success': True,
            'mensagem': 'Período excluído com sucesso!'
        })
        
    except Exception as e:
        mysql.connection.rollback()
        app.logger.error(f"Erro ao excluir período: {str(e)}")
        return jsonify({'success': False, 'erro': str(e)}), 500


# ========== ROTA: Verificar se motorista tem período ativo ==========
@app.route('/api/motoristas/<int:id_motorista>/periodo-ativo')
@login_required
def verificar_periodo_ativo(id_motorista):
    """
    Verifica se o motorista possui um período ativo (DT_FIM NULL)
    """
    try:
        cursor = mysql.connection.cursor()
        
        query = """
        SELECT COUNT(*) 
        FROM CAD_MOTORISTA_PERIODOS 
        WHERE ID_MOTORISTA = %s 
        AND DT_FIM IS NULL
        """
        
        cursor.execute(query, (id_motorista,))
        count = cursor.fetchone()[0]
        cursor.close()
        
        return jsonify({
            'success': True,
            'tem_periodo_ativo': count > 0
        })
        
    except Exception as e:
        app.logger.error(f"Erro ao verificar período ativo: {str(e)}")
        return jsonify({'success': False, 'erro': str(e)}), 500


#### FIM DAS ROTAS DE CADASTRO DE MOTORISTAS ####

@app.route('/controle_locacoes')
@login_required
@verificar_permissao('/controle_locacoes', 'E')
def controle_locacoes():
    return render_template('controle_locacoes.html')

@app.route('/api/tipos_locacao')
@login_required
def api_tipos_locacao():
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT ID_TIPO_LOCACAO, DE_TIPO_LOCACAO
        FROM TIPO_LOCACAO
        WHERE ATIVO = 'S'
        ORDER BY ID_TIPO_LOCACAO
        """
        cursor.execute(query)
        tipos = cursor.fetchall()
        
        resultado = []
        for tipo in tipos:
            resultado.append({
                'ID_TIPO_LOCACAO': tipo[0],
                'DE_TIPO_LOCACAO': tipo[1]
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar tipos de locação: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/processos_locacao')
@login_required
def api_processos_locacao():
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT cl.ID_CL, cl.ANO_EXERCICIO, f.NM_FORNECEDOR, 
               cl.NU_SEI, cl.NU_CONTRATO, f.EMAIL, 
               cl.ID_TIPO_LOCACAO, tl.DE_TIPO_LOCACAO
        FROM CONTROLE_LOCACAO cl
        INNER JOIN CAD_FORNECEDOR f ON f.ID_FORNECEDOR = cl.ID_FORNECEDOR
        INNER JOIN TIPO_LOCACAO tl ON tl.ID_TIPO_LOCACAO = cl.ID_TIPO_LOCACAO
        WHERE cl.ATIVO = 'S'
          AND tl.ATIVO = 'S'
        ORDER BY cl.ID_CL DESC
        """
        cursor.execute(query)
        processos = cursor.fetchall()
        
        # Converter para dicionários
        resultado = []
        for processo in processos:
            resultado.append({
                'ID_CL': processo[0],
                'ANO_EXERCICIO': processo[1],
                'NM_FORNECEDOR': processo[2],
                'NU_SEI': processo[3],
                'NU_CONTRATO': processo[4],
                'EMAIL': processo[5],
                'ID_TIPO_LOCACAO': processo[6],
                'DE_TIPO_LOCACAO': processo[7]
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar processos: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/empenhos/<int:id_cl>')
@login_required
def api_empenhos(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT
            e.ID_EMPENHO,
            e.NU_EMPENHO,
            e.VL_EMPENHO,
            IFNULL(sl.VL_LIQUIDADO, 0) AS VL_LIQUIDADO,
            (e.VL_EMPENHO - IFNULL(sl.VL_LIQUIDADO, 0)) AS VL_SALDO,
            (IFNULL(st.VL_TOTAL, 0) - IFNULL(sl.VL_LIQUIDADO, 0)) AS VL_ALIQUIDAR,
            ((e.VL_EMPENHO - IFNULL(sl.VL_LIQUIDADO, 0)) - (IFNULL(st.VL_TOTAL, 0) - IFNULL(sl.VL_LIQUIDADO, 0))) AS VL_SALDO_DISPONIVEL
        FROM
            CONTROLE_LOCACAO_EMPENHOS e
        LEFT JOIN (
            SELECT
                i.ID_EMPENHO,
                SUM(i.VL_TOTALITEM) AS VL_TOTAL
            FROM CONTROLE_LOCACAO_ITENS i
            GROUP BY i.ID_EMPENHO
        ) st ON e.ID_EMPENHO = st.ID_EMPENHO
        LEFT JOIN (
            SELECT
                i.ID_EMPENHO,
                SUM(i.VL_TOTALITEM) AS VL_LIQUIDADO
            FROM CONTROLE_LOCACAO_ITENS i
            JOIN (
                SELECT
                    ID_EMPENHO,
                    MAX(Mes) AS MesFechado
                FROM (
                    SELECT
                        ID_EMPENHO,
                        DATE_FORMAT(DATA_FIM, '%%Y-%%m') AS Mes,
                        COUNT(*) AS TotalRegistros,
                        SUM(CASE WHEN FL_STATUS='F' THEN 1 ELSE 0 END) AS QtdFechados
                    FROM CONTROLE_LOCACAO_ITENS
                    WHERE DATE_FORMAT(DATA_FIM, '%%Y-%%m') < DATE_FORMAT(CURDATE(), '%%Y-%%m')
                    GROUP BY ID_EMPENHO, Mes
                    HAVING TotalRegistros=QtdFechados
                ) meses_fechados
                GROUP BY ID_EMPENHO
            ) umf ON i.ID_EMPENHO = umf.ID_EMPENHO AND DATE_FORMAT(i.DATA_FIM, '%%Y-%%m') <= umf.MesFechado
            WHERE i.FL_STATUS = 'F'
            GROUP BY i.ID_EMPENHO
        ) sl ON e.ID_EMPENHO = sl.ID_EMPENHO
        WHERE
            e.ATIVO = 'S' AND e.ID_CL = %s
        """
        cursor.execute(query, (id_cl,))
        empenhos = cursor.fetchall()
        
        resultado = []
        for empenho in empenhos:
            resultado.append({
                'ID_EMPENHO': empenho[0],
                'NU_EMPENHO': empenho[1],
                'VL_EMPENHO': float(empenho[2]) if empenho[2] else 0,
                'VL_LIQUIDADO': float(empenho[3]) if empenho[3] else 0,
                'VL_SALDO': float(empenho[4]) if empenho[4] else 0,
                'VL_ALIQUIDAR': float(empenho[5]) if empenho[5] else 0,
                'VL_SALDO_DISPONIVEL': float(empenho[6]) if empenho[6] else 0
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar empenhos: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/sintetico_mensal/<int:id_cl>')
@login_required
def api_sintetico_mensal(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT 
            i.ID_MES, 
            CONCAT((SELECT DE_MES FROM CAD_MES WHERE ID_MES = i.ID_MES),'/',i.ID_EXERCICIO) AS MESANO,
            SUM(i.VL_SUBTOTAL) AS SUBTOTAL, 
            SUM(i.VL_DIFERENCA) AS HORA_EXTRA, 
            SUM(i.VL_TOTALITEM) AS TOTAL,
            SUM(i.KM_RODADO) AS TOTAL_KM
        FROM CONTROLE_LOCACAO_ITENS i
        WHERE i.ID_CL = %s
        GROUP BY i.ID_MES, i.ID_EXERCICIO
        ORDER BY i.ID_MES DESC
        """
        cursor.execute(query, (id_cl,))
        dados = cursor.fetchall()
        
        resultado = []
        for item in dados:
            resultado.append({
                'ID_MES': item[0],
                'MESANO': item[1],
                'SUBTOTAL': float(item[2]) if item[2] else 0,
                'HORA_EXTRA': float(item[3]) if item[3] else 0,
                'TOTAL': float(item[4]) if item[4] else 0,
                'TOTAL_KM': item[5]
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar sintético mensal: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/saldo_diarias/<int:id_cl>')
@login_required
def api_saldo_diarias(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT V.DE_VEICULO, V.VL_DIARIA_KM, V.QT_DK,  
            (SELECT IFNULL(SUM(QT_DIARIA_KM),0)
                FROM CONTROLE_LOCACAO_ITENS
                WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC) AS QT_UTILIZADO,
            IFNULL(V.QT_DK - ( SELECT IFNULL(SUM(QT_DIARIA_KM),0)
                        FROM CONTROLE_LOCACAO_ITENS
                        WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC),0) AS QT_SALDO,
            IFNULL((V.VL_DIARIA_KM * V.QT_DK),0) AS VALOR_TOTAL,
            IFNULL((SELECT CAST(SUM(VL_TOTALITEM) AS DECIMAL(10,2))
                        FROM CONTROLE_LOCACAO_ITENS
                    WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC
                        AND ID_CL = V.ID_CL),0) AS VL_UTILIZADO,
            IFNULL((V.VL_DIARIA_KM * V.QT_DK) -
                    IFNULL((SELECT SUM(VL_TOTALITEM)
                        FROM CONTROLE_LOCACAO_ITENS
                    WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC
                        AND ID_CL = V.ID_CL),0),0) AS VL_SALDO
        FROM CAD_VEICULOS_LOCACAO V
        WHERE ID_CL = %s
        """
        cursor.execute(query, (id_cl,))
        saldos = cursor.fetchall()
        
        # Converter para dicionários
        resultado = []
        for saldo in saldos:
            resultado.append({
                'DE_VEICULO': saldo[0],
                'VL_DIARIA_KM': saldo[1],
                'QT_DK': int(saldo[2]),
                'QT_UTILIZADO': saldo[3],
                'QT_SALDO': saldo[4],
                'VALOR_TOTAL': float(saldo[5]) if saldo[5] else 0,
                'VL_UTILIZADO': float(saldo[6]) if saldo[6] else 0,
                'VL_SALDO': float(saldo[7]) if saldo[7] else 0
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar empenhos: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/api/dados_pls/<int:id_cl>')
@login_required
def api_dados_pls(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT CONCAT(m.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO, 
        COUNT(i.ID_ITEM) AS QTD, 
        SUM(i.VL_TOTALITEM) AS VLTOTAL, i.COMBUSTIVEL,
	SUM(i.KM_RODADO) AS KM 
        FROM CONTROLE_LOCACAO_ITENS i, CAD_MES m
        WHERE m.ID_MES = i.ID_MES AND i.ID_CL = %s
        GROUP BY i.ID_EXERCICIO, i.ID_MES, i.COMBUSTIVEL
        ORDER BY i.ID_EXERCICIO DESC, i.ID_MES DESC
        """
        cursor.execute(query, (id_cl,))
        dadospls = cursor.fetchall()
        
        # Converter para dicionários
        resultado = []
        for pls in dadospls:
            resultado.append({
                'MES_ANO': pls[0],
                'QTD': pls[1],
                'VLTOTAL': float(pls[2]) if pls[2] else 0,
                'COMBUSTIVEL': pls[3],
		'KM': float(pls[4]) if pls[4] else ''
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar empenhos: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/api/locacoes_transito/<int:id_cl>')
@login_required
def api_locacoes_transito(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT
           i.ID_ITEM, i.ID_EXERCICIO, x.NU_MES, x.DE_MES,
           CONCAT(x.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO,
           e.NU_EMPENHO, v.ID_VEICULO_LOC, v.DE_VEICULO,
           i.DS_VEICULO_MOD, i.DT_INICIAL, i.DT_FINAL, 
           i.HR_INICIAL, i.HR_FINAL, i.QT_DIARIA_KM,
           i.VL_DK, i.VL_SUBTOTAL, i.VL_DIFERENCA, i.VL_TOTALITEM,
           i.NU_SEI, i.OBJETIVO, i.SETOR_SOLICITANTE, i.ID_MOTORISTA, 
           CASE WHEN i.ID_MOTORISTA=0
           THEN CONCAT('*',i.NC_CONDUTOR,'*')
           ELSE m.NM_MOTORISTA END AS MOTORISTA, 
           i.FL_EMAIL, i.KM_RODADO, i.COMBUSTIVEL, i.OBS, i.OBS_DEV
        FROM CONTROLE_LOCACAO_ITENS i
        LEFT JOIN CAD_MOTORISTA m
        ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        CAD_VEICULOS_LOCACAO v, CAD_MES x,
        CONTROLE_LOCACAO_EMPENHOS e
        WHERE e.ID_EMPENHO = i.ID_EMPENHO
        AND x.ID_MES = i.ID_MES
        AND v.ID_VEICULO_LOC = i.ID_VEICULO_LOC
        AND i.FL_STATUS = 'T'
        AND i.ID_CL = %s
        ORDER BY i.ID_EXERCICIO DESC, i.ID_MES DESC, i.DATA_INICIO DESC, i.DATA_FIM DESC
        """
        app.logger.info(f"Executando consulta de locações em trânsito para ID_CL={id_cl}")
        cursor.execute(query, (id_cl,))
        locacoes = cursor.fetchall()
        app.logger.info(f"Encontradas {len(locacoes)} locações em trânsito")
        
        # Converter para dicionários
        resultado = []
        for loc in locacoes:
            item = {
                'ID_ITEM': loc[0],
                'ID_EXERCICIO': loc[1],
                'NU_MES': loc[2],
                'DE_MES': loc[3],
                'MES_ANO': loc[4],
                'NU_EMPENHO': loc[5],
                'ID_VEICULO_LOC': loc[6],
                'DE_VEICULO': loc[7],
                'DS_VEICULO_MOD': loc[8],
                'DT_INICIAL': loc[9] if loc[9] else None,
                'DT_FINAL': loc[10] if loc[10] else None,
                'HR_INICIAL': loc[11],
                'HR_FINAL': loc[12],
                'QT_DIARIA_KM': loc[13],
                'VL_DK': float(loc[14]) if loc[14] else 0,
                'VL_SUBTOTAL': float(loc[15]) if loc[15] else 0,
                'VL_DIFERENCA': float(loc[16]) if loc[16] else 0,
                'VL_TOTALITEM': float(loc[17]) if loc[17] else 0,
                'NU_SEI': loc[18],
                'OBJETIVO': loc[19],
                'SETOR_SOLICITANTE': loc[20],
                'ID_MOTORISTA': loc[21],
                'MOTORISTA': loc[22],
                'FL_EMAIL': loc[23],
                'KM_RODADO': loc[24],
                'COMBUSTIVEL': loc[25],
                'OBS': loc[26],
                'OBS_DEV': loc[27]
            }
            resultado.append(item)
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar locações em trânsito: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/api/meses_locacoes/<int:id_cl>')
@login_required
def api_meses_locacoes(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT DISTINCT CONCAT(m.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO 
        FROM CONTROLE_LOCACAO_ITENS i, CAD_MES m 
        WHERE m.ID_MES = i.ID_MES AND i.ID_CL = %s AND i.FL_STATUS = 'F'
        ORDER BY i.ID_EXERCICIO DESC, i.ID_MES DESC
        """
        
        app.logger.info(f"Executando consulta de meses/anos disponíveis para ID_CL={id_cl}")
        cursor.execute(query, (id_cl,))
        meses_anos = cursor.fetchall()
        app.logger.info(f"Encontrados {len(meses_anos)} opções de mês/ano")
        
        # Converter para lista de dicionários
        resultado = []
        for item in meses_anos:
            resultado.append({'MES_ANO': item[0]})
            
        cursor.close()
        return jsonify(resultado)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar opções de mês/ano: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/api/locacoes_finalizadas/<int:id_cl>')
@login_required
def api_locacoes_finalizadas(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """ 
        SELECT i.ID_ITEM, i.ID_EXERCICIO, x.NU_MES, x.DE_MES, CONCAT(x.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO, 
        e.NU_EMPENHO, v.ID_VEICULO_LOC, v.DE_VEICULO, i.DS_VEICULO_MOD, 
        i.DT_INICIAL, i.DT_FINAL, i.HR_INICIAL, i.HR_FINAL, i.QT_DIARIA_KM, 
        i.VL_DK, i.VL_SUBTOTAL, i.VL_DIFERENCA, i.VL_TOTALITEM, i.NU_SEI, 
        i.OBJETIVO, i.SETOR_SOLICITANTE, i.ID_MOTORISTA, 
        CASE WHEN i.ID_MOTORISTA=0 THEN CONCAT('*',i.NC_CONDUTOR,'*') ELSE m.NM_MOTORISTA END AS MOTORISTA, 
        i.FL_EMAIL, i.KM_RODADO, i.COMBUSTIVEL, i.OBS, i.OBS_DEV 
        FROM CONTROLE_LOCACAO_ITENS i 
        LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        CAD_VEICULOS_LOCACAO v, CAD_MES x, CONTROLE_LOCACAO_EMPENHOS e 
        WHERE e.ID_EMPENHO = i.ID_EMPENHO 
        AND x.ID_MES = i.ID_MES 
        AND v.ID_VEICULO_LOC = i.ID_VEICULO_LOC 
        AND i.FL_STATUS = 'F' 
        AND i.ID_CL = %s 
        ORDER BY i.ID_EXERCICIO DESC, i.ID_MES DESC, i.DATA_INICIO DESC, i.DATA_FIM DESC 
        """
        
        app.logger.info(f"Executando consulta de locações finalizadas para ID_CL={id_cl}")
        cursor.execute(query, (id_cl,))
        locacoes = cursor.fetchall()
        app.logger.info(f"Encontradas {len(locacoes)} locações finalizadas")
        
        # Converter para dicionários
        resultado = []
        for loc in locacoes:
            item = {
                'ID_ITEM': loc[0],
                'ID_EXERCICIO': loc[1],
                'NU_MES': loc[2],
                'DE_MES': loc[3],
                'MES_ANO': loc[4],
                'NU_EMPENHO': loc[5],
                'ID_VEICULO_LOC': loc[6],
                'DE_VEICULO': loc[7],
                'DS_VEICULO_MOD': loc[8],
                'DT_INICIAL': loc[9] if loc[9] else None,
                'DT_FINAL': loc[10] if loc[10] else None,
                'HR_INICIAL': loc[11],
                'HR_FINAL': loc[12],
                'QT_DIARIA_KM': loc[13],
                'VL_DK': float(loc[14]) if loc[14] else 0,
                'VL_SUBTOTAL': float(loc[15]) if loc[15] else 0,
                'VL_DIFERENCA': float(loc[16]) if loc[16] else 0,
                'VL_TOTALITEM': float(loc[17]) if loc[17] else 0,
                'NU_SEI': loc[18],
                'OBJETIVO': loc[19],
                'SETOR_SOLICITANTE': loc[20],
                'ID_MOTORISTA': loc[21],
                'MOTORISTA': loc[22],
                'FL_EMAIL': loc[23],
                'KM_RODADO': loc[24],
                'COMBUSTIVEL': loc[25],
                'OBS': loc[26],
                'OBS_DEV': loc[27]
            }
            resultado.append(item)
            
        cursor.close()
        return jsonify(resultado)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar locações finalizadas: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/api/rel_locacao_analitico/<int:id_cl>')
@login_required
def get_rel_locacao_analitico(id_cl):
    try:
        cursor = mysql.connection.cursor()    
        query = """
        SELECT i.ID_ITEM, CONCAT(x.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO, 
        CASE WHEN i.DT_INICIAL=i.DT_FINAL THEN i.DT_INICIAL
        ELSE CONCAT(i.DT_INICIAL,' - ',i.DT_FINAL) END AS PERIODO,
        CONCAT(v.DE_REDUZ,' / ',i.DS_VEICULO_MOD) AS VEICULO, m.NM_MOTORISTA,
        i.QT_DIARIA_KM, i.VL_DK, i.VL_DIFERENCA, i.VL_TOTALITEM, i.KM_RODADO
        FROM CONTROLE_LOCACAO_ITENS i 
        LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        CAD_VEICULOS_LOCACAO v, CAD_MES x, CONTROLE_LOCACAO_EMPENHOS e 
        WHERE e.ID_EMPENHO = i.ID_EMPENHO 
        AND x.ID_MES = i.ID_MES 
        AND v.ID_VEICULO_LOC = i.ID_VEICULO_LOC 
        AND i.FL_STATUS = 'F' 
        AND i.ID_CL = %s
        ORDER BY i.ID_EXERCICIO, i.ID_MES, i.DATA_INICIO, i.DATA_FIM
        """
        
        app.logger.info(f"Executando Relatório para ID_CL={id_cl}")
        cursor.execute(query, (id_cl,))
        items = cursor.fetchall()
        # Converter para dicionários
        resultado = []
        for item in items:
            lista = {
                'ID_ITEM': item[0],
                'MES_ANO': item[1],
                'PERIODO': item[2],
                'VEICULO': item[3],
                'MOTORISTA': item[4],
                'QT_DIARIA_KM': item[5],
                'VL_DK': float(item[6]) if item[6] else 0,
                'VL_DIFERENCA': float(item[7]) if item[7] else 0,
                'VL_TOTALITEM': float(item[8]) if item[8] else 0,
                'KM_RODADO': item[9]
            }
            resultado.append(lista)
            
        cursor.close()
        return jsonify(resultado)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar locações finalizadas: {str(e)}")
        return jsonify({"error": str(e)}), 500
        

@app.route('/rel_locacao_analitico')
@login_required
def rel_locacao_analitico():
    """Gera o relatório analítico de locações como PDF usando ReportLab"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        id_cl = request.args.get('id_cl')
        mes_ano = request.args.get('mes_ano')  # Filtro opcional
        
        if not id_cl:
            return "ID do processo não informado", 400
            
        cursor = mysql.connection.cursor()
        
        # Query base
        query = """
        SELECT i.ID_ITEM, CONCAT(x.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO, 
        CASE WHEN i.DT_INICIAL=i.DT_FINAL THEN i.DT_INICIAL
        ELSE CONCAT(i.DT_INICIAL,' - ',i.DT_FINAL) END AS PERIODO,
        CONCAT(v.DE_REDUZ,' / ',i.DS_VEICULO_MOD) AS VEICULO, m.NM_MOTORISTA,
        i.QT_DIARIA_KM, i.VL_DK, i.VL_DIFERENCA, i.VL_TOTALITEM, i.KM_RODADO
        FROM CONTROLE_LOCACAO_ITENS i 
        LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        CAD_VEICULOS_LOCACAO v, CAD_MES x, CONTROLE_LOCACAO_EMPENHOS e 
        WHERE e.ID_EMPENHO = i.ID_EMPENHO 
        AND x.ID_MES = i.ID_MES 
        AND v.ID_VEICULO_LOC = i.ID_VEICULO_LOC 
        AND i.FL_STATUS = 'F' 
        AND i.ID_CL = %s
        """
        
        # Adicionar filtro de mês/ano se fornecido
        params = [id_cl]
        if mes_ano and mes_ano != 'Todos':
            query += " AND CONCAT(x.DE_MES,'/',i.ID_EXERCICIO) = %s"
            params.append(mes_ano)
            
        query += " ORDER BY i.ID_EXERCICIO, i.ID_MES, i.DATA_INICIO, i.DATA_FIM"
        
        cursor.execute(query, tuple(params))
        items = cursor.fetchall()
        
        # Buscar informações do processo
        cursor.execute("""
            SELECT cl.NU_SEI, cl.NU_CONTRATO, f.NM_FORNECEDOR 
            FROM CONTROLE_LOCACAO cl
            JOIN CAD_FORNECEDOR f ON f.ID_FORNECEDOR = cl.ID_FORNECEDOR
            WHERE cl.ID_CL = %s
        """, (id_cl,))
        processo_info = cursor.fetchone()
        
        cursor.close()
        
        # Criar PDF com margens ajustadas
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(A4), 
                               rightMargin=1*cm, leftMargin=1*cm,
                               topMargin=1*cm, bottomMargin=1*cm)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Título
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                     fontSize=16, textColor=colors.HexColor('#1a73e8'),
                                     spaceAfter=8, alignment=TA_CENTER, fontName='Helvetica-Bold')
        
        elements.append(Paragraph('Relatório de Locações - Analítico', title_style))
        
        # Informações do fornecedor (alinhado à esquerda como a tabela)
        if processo_info:
            info_style = ParagraphStyle('InfoStyle', parent=styles['Normal'],
                                       fontSize=9, spaceAfter=2, alignment=TA_LEFT,
                                       leftIndent=0)
            
            fornecedor_text = f'<b>Fornecedor:</b> {processo_info[2]}'
            elements.append(Paragraph(fornecedor_text, info_style))
            
            if mes_ano and mes_ano != 'Todos':
                periodo_text = f'<b>Período:</b> {mes_ano}'
                elements.append(Paragraph(periodo_text, info_style))
        
        elements.append(Spacer(1, 0.5*cm))
        
        # Verificar se deve agrupar por mês (quando não tem filtro)
        agrupar_mes = not (mes_ano and mes_ano != 'Todos')
        
        # Larguras de colunas padronizadas para ambos os modos
        col_widths = [0.9*cm, 2.5*cm, 3.5*cm, 6*cm, 4.7*cm, 1.5*cm, 2.1*cm, 2.0*cm, 2.3*cm, 2*cm]
        
        if items:
            if agrupar_mes:
                # Agrupar itens por mês/ano
                meses_dict = {}
                for item in items:
                    mes_ano_key = item[1]  # MES_ANO
                    if mes_ano_key not in meses_dict:
                        meses_dict[mes_ano_key] = []
                    meses_dict[mes_ano_key].append(item)
                
                total_geral_diarias = 0
                total_geral_valor = 0
                total_geral_km = 0
                
                for mes_ano_key in sorted(meses_dict.keys()):
                    # Título do mês - com largura total igual à tabela
                    mes_table_data = [[mes_ano_key]]
                    mes_table = Table(mes_table_data, colWidths=[sum(col_widths)])
                    mes_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#4472C4')),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
                        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 11),
                        ('LEFTPADDING', (0, 0), (-1, -1), 5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                        ('TOPPADDING', (0, 0), (-1, -1), 5),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ]))
                    elements.append(mes_table)
                    elements.append(Spacer(1, 0.1*cm))
                    
                    # Cabeçalho da tabela
                    data = [['Item', 'Mês/Ano', 'Período', 'Veículo', 'Motorista', 
                            'Qtde', 'Valor Diária', 'Valor Dif.', 'Valor Total', 'Km Rodado']]
                    
                    subtotal_diarias = 0
                    subtotal_valor = 0
                    subtotal_km = 0
                    
                    for idx, item in enumerate(meses_dict[mes_ano_key], 1):
                        subtotal_diarias += item[5] if item[5] else 0
                        subtotal_valor += item[8] if item[8] else 0
                        subtotal_km += item[9] if item[9] else 0
                        
                        # Formatar valores no padrão brasileiro
                        qtde_str = f"{item[5]:.2f}".replace('.', ',') if item[5] else '0,00'
                        vl_diaria_str = f"R$ {item[6]:.2f}".replace('.', ',') if item[6] else 'R$ 0,00'
                        vl_dif_str = f"R$ {item[7]:.2f}".replace('.', ',') if item[7] else 'R$ 0,00'
                        vl_total_str = f"R$ {item[8]:.2f}".replace('.', ',') if item[8] else 'R$ 0,00'
                        
                        # Criar parágrafos para permitir quebra de linha
                        veiculo_para = Paragraph(item[3] or '-', ParagraphStyle('Normal', fontSize=7, leading=9))
                        motorista_para = Paragraph(item[4] or '-', ParagraphStyle('Normal', fontSize=7, leading=9))
                        
                        data.append([
                            str(idx),
                            item[1] or '-',
                            item[2] or '-',
                            veiculo_para,
                            motorista_para,
                            qtde_str,
                            vl_diaria_str,
                            vl_dif_str,
                            vl_total_str,
                            f"{item[9]:.0f}" if item[9] else '-'
                        ])
                    
                    # Subtotal do mês (formato brasileiro)
                    subtotal_qtde = f"{subtotal_diarias:.2f}".replace('.', ',')
                    subtotal_vl = f"R$ {subtotal_valor:.2f}".replace('.', ',')
                    subtotal_km_str = f"{subtotal_km:.0f}"
                    
                    data.append(['', '', '', '', f'Subtotal {mes_ano_key}:', 
                                subtotal_qtde, '', '', subtotal_vl, subtotal_km_str])
                    
                    total_geral_diarias += subtotal_diarias
                    total_geral_valor += subtotal_valor
                    total_geral_km += subtotal_km

                    # Criar tabela com larguras padronizadas e repeatRows
                    table = Table(data, colWidths=col_widths, repeatRows=1)
                    
                    table.setStyle(TableStyle([
                        # Cabeçalho
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 7),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
                        ('TOPPADDING', (0, 0), (-1, 0), 5),
                        # Corpo da tabela
                        ('BACKGROUND', (0, 1), (-1, -2), colors.white),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
                        ('FONTSIZE', (0, 1), (-1, -1), 7),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 3),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                        ('TOPPADDING', (0, 1), (-1, -2), 2),
                        ('BOTTOMPADDING', (0, 1), (-1, -2), 2),
                        # Alinhamentos
                        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Item
                        ('ALIGN', (1, 1), (1, -1), 'CENTER'),  # Mês/Ano
                        ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Período
                        ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Qtde
                        ('ALIGN', (6, 1), (6, -1), 'RIGHT'),   # Valor Diária
                        ('ALIGN', (7, 1), (7, -1), 'RIGHT'),   # Valor Dif
                        ('ALIGN', (8, 1), (8, -1), 'RIGHT'),   # Valor Total
                        ('ALIGN', (9, 1), (9, -1), 'CENTER'),  # Km Rodado
                        # Subtotal
                        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#D9E1F2')),
                        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, -1), (-1, -1), 7),
                        ('ALIGN', (4, -1), (4, -1), 'RIGHT'),
                    ]))
                    
                    elements.append(table)
                    elements.append(Spacer(1, 0.3*cm))
                
                # Total geral (formato brasileiro)
                total_qtde = f"{total_geral_diarias:.2f}".replace('.', ',')
                total_vl = f"R$ {total_geral_valor:.2f}".replace('.', ',')
                total_km_str = f"{total_geral_km:.0f}"
                
                data_total = [['', '', '', '', 'Total Geral:', 
                              total_qtde, '', '', total_vl, total_km_str]]
                
                table_total = Table(data_total, colWidths=col_widths)
                table_total.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#B4C7E7')),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 8),
                    ('ALIGN', (4, 0), (4, 0), 'RIGHT'),
                    ('ALIGN', (5, 0), (5, 0), 'CENTER'),
                    ('ALIGN', (8, 0), (8, 0), 'RIGHT'),
                    ('ALIGN', (9, 0), (9, 0), 'CENTER'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
                    ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, 0), 3),
                    ('RIGHTPADDING', (0, 0), (-1, 0), 3),
                    ('TOPPADDING', (0, 0), (-1, 0), 5),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
                ]))
                elements.append(table_total)
                
            else:
                # Sem agrupamento - mostrar tudo numa tabela única com formatação padronizada
                data = [['Item', 'Mês/Ano', 'Período', 'Veículo', 'Motorista', 
                        'Qtde', 'Valor Diária', 'Valor Dif.', 'Valor Total', 'Km Rodado']]
                
                total_diarias = 0
                total_valor = 0
                total_km = 0
                
                for idx, item in enumerate(items, 1):
                    total_diarias += item[5] if item[5] else 0
                    total_valor += item[8] if item[8] else 0
                    total_km += item[9] if item[9] else 0
                    
                    # Formatar valores no padrão brasileiro
                    qtde_str = f"{item[5]:.2f}".replace('.', ',') if item[5] else '0,00'
                    vl_diaria_str = f"R$ {item[6]:.2f}".replace('.', ',') if item[6] else 'R$ 0,00'
                    vl_dif_str = f"R$ {item[7]:.2f}".replace('.', ',') if item[7] else 'R$ 0,00'
                    vl_total_str = f"R$ {item[8]:.2f}".replace('.', ',') if item[8] else 'R$ 0,00'
                    
                    # Criar parágrafos para permitir quebra de linha
                    veiculo_para = Paragraph(item[3] or '-', ParagraphStyle('Normal', fontSize=7, leading=9))
                    motorista_para = Paragraph(item[4] or '-', ParagraphStyle('Normal', fontSize=7, leading=9))
                    
                    data.append([
                        str(idx),
                        item[1] or '-',
                        item[2] or '-',
                        veiculo_para,
                        motorista_para,
                        qtde_str,
                        vl_diaria_str,
                        vl_dif_str,
                        vl_total_str,
                        f"{item[9]:.0f}" if item[9] else '-'
                    ])
                
                # Total (formato brasileiro)
                total_qtde = f"{total_diarias:.2f}".replace('.', ',')
                total_vl = f"R$ {total_valor:.2f}".replace('.', ',')
                total_km_str = f"{total_km:.0f}"
                
                data.append(['', '', '', '', 'Total Geral:', 
                            total_qtde, '', '', total_vl, total_km_str])
                
                # Criar tabela com larguras padronizadas e repeatRows
                table = Table(data, colWidths=col_widths, repeatRows=1)
                
                table.setStyle(TableStyle([
                    # Cabeçalho
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 7),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
                    ('TOPPADDING', (0, 0), (-1, 0), 5),
                    # Corpo da tabela
                    ('BACKGROUND', (0, 1), (-1, -2), colors.white),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
                    ('FONTSIZE', (0, 1), (-1, -1), 7),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 3),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                    ('TOPPADDING', (0, 1), (-1, -2), 2),
                    ('BOTTOMPADDING', (0, 1), (-1, -2), 2),
                    # Alinhamentos
                    ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Item
                    ('ALIGN', (1, 1), (1, -1), 'CENTER'),  # Mês/Ano
                    ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Período
                    ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Qtde
                    ('ALIGN', (6, 1), (6, -1), 'RIGHT'),   # Valor Diária
                    ('ALIGN', (7, 1), (7, -1), 'RIGHT'),   # Valor Dif
                    ('ALIGN', (8, 1), (8, -1), 'RIGHT'),   # Valor Total
                    ('ALIGN', (9, 1), (9, -1), 'CENTER'),  # Km Rodado
                    # Total
                    ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#B4C7E7')),
                    ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, -1), (-1, -1), 8),
                    ('ALIGN', (4, -1), (4, -1), 'RIGHT'),
                ]))
                
                elements.append(table)
        else:
            # Sem dados
            sem_dados_style = ParagraphStyle('SemDados', parent=styles['Normal'],
                                            fontSize=11, textColor=colors.grey,
                                            alignment=TA_CENTER, spaceAfter=20, spaceBefore=20)
            elements.append(Paragraph('Nenhuma locação finalizada encontrada para os critérios selecionados.', 
                                    sem_dados_style))
        
        # Rodapé
        elements.append(Spacer(1, 0.5*cm))
        data_geracao = datetime.now().strftime('%d/%m/%Y às %H:%M')
        footer_style = ParagraphStyle('Footer', parent=styles['Normal'],
                                     fontSize=9, textColor=colors.grey,
                                     alignment=TA_CENTER)
        elements.append(Paragraph(f'Relatório gerado em {data_geracao}', footer_style))
        
        # Gerar PDF
        doc.build(elements)
        pdf_buffer.seek(0)
        
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=relatorio_locacoes_{id_cl}.pdf'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Erro ao gerar relatório: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return f"Erro ao gerar relatório: {str(e)}", 500		

# Rota para listar veículos disponíveis por ID_CL
@app.route('/api/lista_veiculo')
@login_required
def listar_veiculos():
    try:
        id_cl = request.args.get('id_cl')
        if not id_cl:
            return jsonify({'erro': 'ID_CL não fornecido'}), 400
            
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT ID_VEICULO_LOC, DE_VEICULO, VL_DIARIA_KM FROM CAD_VEICULOS_LOCACAO WHERE ID_CL = %s", (id_cl,))
        
        veiculos = []
        for row in cursor.fetchall():
            veiculos.append({
                'ID_VEICULO_LOC': row[0],
                'DE_VEICULO': row[1],
                'VL_DIARIA_KM': float(row[2]) if row[2] else 0.0
            })
            
        cursor.close()
        return jsonify(veiculos)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/setores_loc')
@login_required
def listar_setores_loc():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT SIGLA_SETOR FROM CAD_SETORES ORDER BY SIGLA_SETOR")
               
        items = cursor.fetchall()
        setores = []
        for item in items:
            lista = {'SIGLA_SETOR': item[0]}
            setores.append(lista)
            
        cursor.close()
        return jsonify(setores)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar locações finalizadas: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
# Rota para listar motoristas
@app.route('/api/lista_motorista_loc')
@login_required
def listar_motoristas_loc():
    try:
        print("Iniciando consulta à lista de motoristas")
        cursor = mysql.connection.cursor()
        
        print("Executando consulta SQL")
        cursor.execute("""
            SELECT ID_MOTORISTA, NM_MOTORISTA, NU_TELEFONE, 
            FILE_PDF, NOME_ARQUIVO FROM CAD_MOTORISTA
            WHERE ID_MOTORISTA <> 0 AND ATIVO = 'S' ORDER BY NM_MOTORISTA
        """)
        
        results = cursor.fetchall()
        print(f"Quantidade de resultados encontrados: {len(results)}")
        
        if len(results) > 0:
            print(f"Primeiro registro: ID={results[0][0]}, Nome={results[0][1]}")
        
        motoristas = []
        for i, row in enumerate(results):
            try:
                # Verificar se FILE_PDF é None antes de processar
                file_pdf = row[3] if row[3] is not None else None
                
                motorista = {
                    'ID_MOTORISTA': row[0],
                    'NM_MOTORISTA': row[1],
                    'NU_TELEFONE': row[2],
                    'FILE_PDF': file_pdf is not None,  # Apenas indicar presença, não enviar arquivo
                    'NOME_ARQUIVO': row[4]
                }
                motoristas.append(motorista)
            except Exception as row_error:
                print(f"Erro ao processar linha {i}: {str(row_error)}")
        
        cursor.close()
        return jsonify(motoristas)
    except Exception as e:
        print(f"ERRO COMPLETO: {str(e)}")
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/empenhos_loc')
@login_required
def api_empenhos_loc():
    try:
        id_cl = request.args.get('id_cl')
        if not id_cl:
            return jsonify({'erro': 'ID_CL não fornecido'}), 400
        cursor = mysql.connection.cursor()
        query = """
        SELECT ID_EMPENHO, NU_EMPENHO
        FROM CONTROLE_LOCACAO_EMPENHOS
        WHERE ATIVO = 'S'
        AND ID_CL = %s
        """
        cursor.execute(query, (id_cl,))
        empenhos = cursor.fetchall()
        
        # Converter para dicionários
        resultado = []
        for empenho in empenhos:
            resultado.append({
                'ID_EMPENHO': empenho[0],
                'NU_EMPENHO': empenho[1]
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar empenhos: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
# Rota para obter o próximo ID_ITEM
def obter_proximo_id_item():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT MAX(ID_ITEM) FROM CONTROLE_LOCACAO_ITENS")
    resultado = cursor.fetchone()
    cursor.close()
    
    ultimo_id = resultado[0] if resultado[0] else 0
    return ultimo_id + 1

#####....#####.....

@app.route('/api/verificar_vinculo_locacao', methods=['GET'])
@login_required
def verificar_vinculo_locacao():
    """
    Verifica se existe vínculo de locação para o tipo de veículo
    e retorna os dados necessários
    """
    try:
        id_tipoveiculo = request.args.get('id_tipoveiculo')
        id_motorista = request.args.get('id_motorista')
        
        if not id_tipoveiculo or not id_motorista:
            return jsonify({'tem_vinculo': False})
        
        # Verificar se motorista é válido (> 0)
        if int(id_motorista) <= 0:
            return jsonify({'tem_vinculo': False})
        
        cursor = mysql.connection.cursor()
        
        # SQL 1: Buscar vínculo de locação
        sql_vinculo = """
            SELECT ID_VEICULO_LOC, VL_DIARIA_KM, DE_VEICULO 
            FROM CAD_VEICULOS_LOCACAO
            WHERE ID_TIPOVEICULO = %s
        """
        cursor.execute(sql_vinculo, (id_tipoveiculo,))
        vinculo = cursor.fetchone()
        
        if not vinculo:
            cursor.close()
            return jsonify({'tem_vinculo': False})
        
        id_veiculo_loc = vinculo[0]
        vl_diaria_km = float(vinculo[1])
        de_veiculo_loc = vinculo[2]
        
        
        # SQL 2: Buscar empenhos ativos
        sql_empenhos = """
            SELECT ID_EMPENHO, NU_EMPENHO 
            FROM CONTROLE_LOCACAO_EMPENHOS
            WHERE ATIVO = 'S' AND ID_CL = 3
            ORDER BY NU_EMPENHO
        """
        cursor.execute(sql_empenhos)
        empenhos_raw = cursor.fetchall()
        
        empenhos = [
            {
                'id': emp[0],
                'numero': emp[1]
            }
            for emp in empenhos_raw
        ]
        
        # Verificar CNH do motorista
        sql_cnh = """
            SELECT FILE_PDF 
            FROM CAD_MOTORISTA 
            WHERE ID_MOTORISTA = %s
        """
        cursor.execute(sql_cnh, (id_motorista,))
        motorista_cnh = cursor.fetchone()
        
        tem_cnh = bool(motorista_cnh and motorista_cnh[0])
        
        cursor.close()
        
        return jsonify({
            'tem_vinculo': True,
            'id_veiculo_loc': id_veiculo_loc,
            'vl_diaria_km': vl_diaria_km,
            'empenhos': empenhos,
            'tem_cnh': tem_cnh,
            'de_veiculo_loc': de_veiculo_loc,
            'id_cl': 3 # ID fixo conforme SQL    
        })
        
    except Exception as e:
        print(f"Erro ao verificar vínculo de locação: {str(e)}")
        return jsonify({'erro': str(e), 'tem_vinculo': False}), 500





@app.route('/api/verificar_vinculo_fornecedor', methods=['GET'])
@login_required
def verificar_vinculo_fornecedor():
    """
    Verifica se o tipo de veículo tem vínculo com fornecedor (sem CAD_VEICULOS_LOCACAO)
    Busca item do fornecedor baseado no ID_TIPOVEICULO
    """
    cursor = None
    try:
        id_tipoveiculo = request.args.get('id_tipoveiculo')
        
        if not id_tipoveiculo:
            return jsonify({'tem_vinculo': False}), 400
        
        cursor = mysql.connection.cursor()
        
        # Verificar se tem vínculo com CAD_VEICULOS_LOCACAO (se tiver, não entra na nova regra)
        cursor.execute("""
            SELECT COUNT(*) 
            FROM CAD_VEICULOS_LOCACAO 
            WHERE ID_TIPOVEICULO = %s
        """, (id_tipoveiculo,))
        
        tem_vinculo_locacao = cursor.fetchone()[0] > 0
        
        if tem_vinculo_locacao:
            return jsonify({'tem_vinculo': False, 'tipo': 'locacao_existente'})
        
        # Verificar se tem fornecedor vinculado com email e buscar item correspondente
        cursor.execute("""
            SELECT 
                tv.ID_FORNECEDOR,
                f.EMAIL,
                f.NM_FORNECEDOR,
                tv.DE_TIPOVEICULO,
                fi.IDITEM,
                fi.DESCRICAO,
                cl.ID_CL
            FROM TIPO_VEICULO tv
            INNER JOIN CAD_FORNECEDOR f ON f.ID_FORNECEDOR = tv.ID_FORNECEDOR
            LEFT JOIN CAD_FORNECEDOR_ITEM fi ON fi.ID_FORNECEDOR = tv.ID_FORNECEDOR 
                                             AND fi.ID_TIPOVEICULO = tv.ID_TIPOVEICULO
            LEFT JOIN CONTROLE_LOCACAO cl ON cl.ID_FORNECEDOR = tv.ID_FORNECEDOR 
            WHERE cl.ATIVO = 'S'
              AND tv.ID_TIPOVEICULO = %s 
              AND tv.ID_FORNECEDOR IS NOT NULL
              AND f.EMAIL IS NOT NULL
              AND f.EMAIL != ''
        """, (id_tipoveiculo,))
        
        resultado = cursor.fetchone()
        
        if resultado:
            return jsonify({
                'tem_vinculo': True,
                'tipo': 'fornecedor',
                'id_fornecedor': resultado[0],
                'email_fornecedor': resultado[1],
                'nome_fornecedor': resultado[2],
                'de_tipoveiculo': resultado[3],
                'iditem': resultado[4] if resultado[4] else 0,
                'descricao_item': resultado[5] if resultado[5] else resultado[3],  # Usa descrição do item ou tipo veículo
                'id_cl': resultado[6]
            })
        
        return jsonify({'tem_vinculo': False})
        
    except Exception as e:
        app.logger.error(f"Erro ao verificar vínculo com fornecedor: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/verificar_vinculo_diarias', methods=['GET'])
@login_required
def verificar_vinculo_diarias():
    """
    Verifica se motorista é terceirizado e tem fornecedor com email cadastrado
    Para solicitação de diárias de viagem
    """
    cursor = None
    try:
        id_motorista = request.args.get('id_motorista')
        
        if not id_motorista or int(id_motorista) <= 0:
            return jsonify({'tem_vinculo': False}), 400
        
        cursor = mysql.connection.cursor()
        
        # Verificar se motorista é terceirizado e tem fornecedor com email + VL_DIARIA
        cursor.execute("""
            SELECT 
                m.ID_MOTORISTA,
                m.NM_MOTORISTA,
                m.TIPO_CADASTRO,
                m.ID_FORNECEDOR,
                f.EMAIL,
                f.NM_FORNECEDOR,
                f.VL_DIARIA
            FROM CAD_MOTORISTA m
            INNER JOIN CAD_FORNECEDOR f ON f.ID_FORNECEDOR = m.ID_FORNECEDOR
            WHERE m.ID_MOTORISTA = %s
              AND m.TIPO_CADASTRO = 'Terceirizado'
              AND m.ATIVO = 'S'
              AND m.ID_FORNECEDOR IS NOT NULL
              AND f.EMAIL IS NOT NULL
              AND f.EMAIL != ''
              AND f.VL_DIARIA IS NOT NULL
              AND f.VL_DIARIA > 0
        """, (id_motorista,))
        
        resultado = cursor.fetchone()
        
        if resultado:
            return jsonify({
                'tem_vinculo': True,
                'id_motorista': resultado[0],
                'nome_motorista': resultado[1],
                'tipo_cadastro': resultado[2],
                'id_fornecedor': resultado[3],
                'email_fornecedor': resultado[4],
                'nome_fornecedor': resultado[5],
                'vl_diaria': float(resultado[6])
            })
        
        return jsonify({'tem_vinculo': False})
        
    except Exception as e:
        app.logger.error(f"Erro ao verificar vínculo de diárias: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/verificar_locacao_existente', methods=['GET'])
@login_required
def verificar_locacao_existente():
    """
    Verifica se já existe locação solicitada para uma demanda
    Baseado no motorista e período da demanda
    """
    try:
        id_motorista = request.args.get('id_motorista')
        dt_inicio = request.args.get('dt_inicio')
        dt_fim = request.args.get('dt_fim')
        
        if not all([id_motorista, dt_inicio, dt_fim]):
            return jsonify({'tem_locacao': False})
        
        cursor = mysql.connection.cursor()
        
        # Verificar se existe locação no período
        sql = """
            SELECT COUNT(*) as total
            FROM CONTROLE_LOCACAO_ITENS
            WHERE ID_MOTORISTA = %s
            AND DT_INICIAL <= %s
            AND DT_FINAL >= %s
            AND FL_STATUS = 'T'  -- T = em trânsito
        """
        
        cursor.execute(sql, (id_motorista, dt_fim, dt_inicio))
        resultado = cursor.fetchone()
        cursor.close()
        
        tem_locacao = resultado[0] > 0 if resultado else False
        
        return jsonify({'tem_locacao': tem_locacao})
        
    except Exception as e:
        print(f"Erro ao verificar locação existente: {str(e)}")
        return jsonify({'erro': str(e), 'tem_locacao': False}), 500


@app.route('/api/usuario_logado', methods=['GET'])
@login_required
def obter_usuario_logado():
    """Retorna informações do usuário logado"""
    return jsonify({
        'nome': session.get('usuario_nome', 'Administrador'),
        'login': session.get('usuario_login', '')
    })


@app.route('/api/salvar_diaria_terceirizado', methods=['POST'])
@login_required
def salvar_diaria_terceirizado():
    """
    Salva ou atualiza registro de diária de motorista terceirizado
    IDITEM é obtido manualmente via SELECT MAX(IDITEM) + 1
    """
    cursor = None
    try:
        data = request.get_json()
        
        id_ad = data.get('id_ad')
        id_fornecedor = data.get('id_fornecedor')
        id_motorista = data.get('id_motorista')
        qt_diarias = data.get('qt_diarias')
        vl_diaria = data.get('vl_diaria')
        vl_total = data.get('vl_total')
        
        app.logger.info(f"=== SALVAR DIÁRIA TERCEIRIZADO ===")
        app.logger.info(f"ID_AD: {id_ad}")
        app.logger.info(f"ID_FORNECEDOR: {id_fornecedor}")
        app.logger.info(f"ID_MOTORISTA: {id_motorista}")
        app.logger.info(f"QT_DIARIAS: {qt_diarias}")
        
        if not all([id_ad, id_fornecedor, id_motorista, qt_diarias, vl_diaria, vl_total]):
            app.logger.error("Dados incompletos")
            return jsonify({'erro': 'Dados incompletos', 'success': False}), 400
        
        cursor = mysql.connection.cursor()
        
        # Verificar se já existe registro para esse ID_AD
        cursor.execute("""
            SELECT IDITEM FROM DIARIAS_TERCEIRIZADOS WHERE ID_AD = %s
        """, (id_ad,))
        
        registro_existente = cursor.fetchone()
        
        if registro_existente:
            # ATUALIZAR registro existente
            app.logger.info(f"Atualizando registro existente - IDITEM: {registro_existente[0]}")
            
            cursor.execute("""
                UPDATE DIARIAS_TERCEIRIZADOS
                SET ID_FORNECEDOR = %s,
                    ID_MOTORISTA = %s,
                    QT_DIARIAS = %s,
                    VL_DIARIA = %s,
                    VL_TOTAL = %s
                WHERE ID_AD = %s
            """, (id_fornecedor, id_motorista, qt_diarias, vl_diaria, vl_total, id_ad))
            
            iditem = registro_existente[0]
            
        else:
            # ===== OBTER PRÓXIMO IDITEM MANUALMENTE =====
            cursor.execute("SELECT MAX(IDITEM) FROM DIARIAS_TERCEIRIZADOS")
            resultado = cursor.fetchone()
            
            if resultado and resultado[0]:
                iditem = resultado[0] + 1
            else:
                iditem = 1  # Primeira diária
            
            app.logger.info(f"Próximo IDITEM: {iditem}")
            
            # INSERIR novo registro com IDITEM manual
            cursor.execute("""
                INSERT INTO DIARIAS_TERCEIRIZADOS
                (IDITEM, ID_AD, ID_FORNECEDOR, ID_MOTORISTA, QT_DIARIAS, VL_DIARIA, VL_TOTAL, FL_EMAIL)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'N')
            """, (iditem, id_ad, id_fornecedor, id_motorista, qt_diarias, vl_diaria, vl_total))
            
            app.logger.info(f"Novo registro inserido - IDITEM: {iditem}")
        
        mysql.connection.commit()
        
        # ===== EMITIR WEBSOCKET =====
        usuario_atual = session.get('usuario_login', '')
        
        try:
            payload = {
                'tipo': 'INSERT' if not registro_existente else 'UPDATE',
                'entidade': 'DIARIA_TERCEIRIZADO',
                'iditem': iditem,
                'id_ad': id_ad,
                'usuario': usuario_atual,
                'timestamp': datetime.now().isoformat()
            }
            
            socketio.emit('alteracao_agenda', payload, room='agenda')
            
            print(f"📡 WebSocket: {payload['tipo']} DIARIA_TERCEIRIZADO - IDITEM: {iditem}")
            
        except Exception as e:
            print(f"❌ Erro ao emitir WebSocket: {str(e)}")
        
        app.logger.info(f"✅ Diária salva com sucesso - IDITEM: {iditem}")
        
        return jsonify({
            'success': True,
            'iditem': iditem,
            'mensagem': 'Diária salva com sucesso'
        })
        
    except Exception as e:
        if cursor:
            mysql.connection.rollback()
        app.logger.error(f"❌ Erro ao salvar diária: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'erro': str(e), 'success': False}), 500
    finally:
        if cursor:
            cursor.close()

			
@app.route('/api/excluir_diaria_terceirizado/<int:id_ad>', methods=['DELETE'])
@login_required
def excluir_diaria_terceirizado(id_ad):
    """
    Exclui registro de diária quando demanda muda ou é excluída
    """
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        # Excluir registro de diária
        cursor.execute("""
            DELETE FROM DIARIAS_TERCEIRIZADOS WHERE ID_AD = %s
        """, (id_ad,))
        
        mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'mensagem': 'Diária excluída com sucesso'
        })
        
    except Exception as e:
        if cursor:
            mysql.connection.rollback()
        app.logger.error(f"Erro ao excluir diária: {str(e)}")
        return jsonify({'erro': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

@app.route('/api/verificar_diaria_solicitada', methods=['GET'])
@login_required
def verificar_diaria_solicitada():
    """
    Verifica se já existe registro de diária e se email já foi enviado
    """
    cursor = None
    try:
        id_ad = request.args.get('id_ad')
        
        if not id_ad:
            return jsonify({'tem_diaria': False}), 400
        
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT 
                IDITEM,
                FL_EMAIL,
                QT_DIARIAS,
                VL_DIARIA,
                VL_TOTAL
            FROM DIARIAS_TERCEIRIZADOS
            WHERE ID_AD = %s
        """, (id_ad,))
        
        resultado = cursor.fetchone()
        
        if resultado:
            return jsonify({
                'tem_diaria': True,
                'iditem': resultado[0],
                'email_enviado': resultado[1] == 'S',
                'qt_diarias': float(resultado[2]),
                'vl_diaria': float(resultado[3]),
                'vl_total': float(resultado[4])
            })
        
        return jsonify({'tem_diaria': False})
        
    except Exception as e:
        app.logger.error(f"Erro ao verificar diária solicitada: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

#####....#####.....
    
@app.route('/api/nova_locacao', methods=['POST'])
@login_required
def nova_locacao():
    try:
        # Obter dados do formulário
        id_cl = request.form.get('id_cl')
        id_empenho = request.form.get('empenho')
        setor_solicitante = request.form.get('setor_solicitante')
        objetivo = request.form.get('objetivo')
        id_veiculo_loc = request.form.get('id_veiculo_loc')
        id_motorista = request.form.get('id_motorista')
        data_inicio = request.form.get('data_inicio')
        data_fim = request.form.get('data_fim')
        hora_inicio = request.form.get('hora_inicio')
        qt_diaria_km = request.form.get('qt_diaria_km')
        vl_dk = request.form.get('vl_dk')
        vl_totalitem = request.form.get('vl_totalitem')
        nu_sei = request.form.get('nu_sei')
        obs = request.form.get('obs')
        
        # Obter o próximo ID_ITEM
        id_item = obter_proximo_id_item()
        
        # Converter data_inicio e data_fim para objetos datetime
        data_inicio_obj = datetime.strptime(data_inicio, '%Y-%m-%d')
        data_fim_obj = datetime.strptime(data_fim, '%Y-%m-%d')
        
        # Extrair ano e mês da data de fim
        id_exercicio = data_fim_obj.year
        id_mes = data_fim_obj.month
        
        # Converter data para o formato dd/mm/yyyy para os campos de string
        dt_inicial = data_inicio_obj.strftime('%d/%m/%Y')
        dt_final = data_fim_obj.strftime('%d/%m/%Y')
        
        # Converter hora para string no formato hh:mm
        hr_inicial = hora_inicio
        
        # Obter ID do usuário da sessão
        usuario = session.get('usuario_login')
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Verificar se o motorista tem CNH cadastrada
        cursor.execute("SELECT FILE_PDF, NM_MOTORISTA, NU_TELEFONE, NOME_ARQUIVO, EMAIL FROM CAD_MOTORISTA WHERE ID_MOTORISTA = %s", (id_motorista,))
        motorista_info = cursor.fetchone()
        
        # Buscar o email do fornecedor
        cursor.execute("SELECT EMAIL FROM CAD_FORNECEDOR f INNER JOIN CONTROLE_LOCACAO cl ON f.ID_FORNECEDOR = cl.ID_FORNECEDOR WHERE cl.ID_CL = %s", (id_cl,))
        fornecedor_info = cursor.fetchone()
        email_fornecedor = fornecedor_info['EMAIL'] if fornecedor_info and fornecedor_info['EMAIL'] else None
        
        if not email_fornecedor:
            cursor.close()
            return jsonify({
                'sucesso': False,
                'mensagem': 'Email do fornecedor não cadastrado. Por favor, configure o email do fornecedor antes de solicitar locações.'
            }), 400
        
        # Verificar se é necessário salvar a CNH
        file_pdf = motorista_info['FILE_PDF'] if motorista_info['FILE_PDF'] else None
        nome_arquivo_cnh = motorista_info['NOME_ARQUIVO'] if motorista_info['NOME_ARQUIVO'] else None
        
        if not file_pdf and 'file_cnh' in request.files:
            file_cnh = request.files['file_cnh']
            
            if file_cnh and file_cnh.filename != '':
                # Salvar o conteúdo do arquivo
                file_content = file_cnh.read()
                nome_arquivo_cnh = file_cnh.filename
                
                # Atualizar o motorista com o arquivo da CNH
                cursor.execute(
                    "UPDATE CAD_MOTORISTA SET FILE_PDF = %s, NOME_ARQUIVO = %s WHERE ID_MOTORISTA = %s",
                    (file_content, nome_arquivo_cnh, id_motorista)
                )
                mysql.connection.commit()
                file_pdf = file_content
        
        # Inserir na tabela CONTROLE_LOCACAO_ITENS
        cursor.execute("""
            INSERT INTO CONTROLE_LOCACAO_ITENS (
                ID_ITEM, ID_CL, ID_EXERCICIO, ID_EMPENHO, SETOR_SOLICITANTE, OBJETIVO, ID_MES, 
                ID_VEICULO_LOC, DS_VEICULO_MOD, ID_MOTORISTA, DATA_INICIO, DATA_FIM, HORA_INICIO, 
                QT_DIARIA_KM, VL_DK, VL_SUBTOTAL, VL_TOTALITEM, NU_SEI, FL_EMAIL, 
                OBS, FL_STATUS, USUARIO, DT_INICIAL, DT_FINAL, HR_INICIAL, COMBUSTIVEL
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '',%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '')
        """, (
            id_item, id_cl, id_exercicio, id_empenho, setor_solicitante, objetivo, id_mes, 
            id_veiculo_loc, id_motorista, data_inicio, data_fim, hora_inicio, 
            qt_diaria_km, vl_dk, vl_totalitem, vl_totalitem, nu_sei, 'N', 
            obs, 'T', usuario, dt_inicial, dt_final, hr_inicial
        ))
        mysql.connection.commit()
        
        # Obter informações do veículo
        cursor.execute("SELECT DE_VEICULO FROM CAD_VEICULOS_LOCACAO WHERE ID_VEICULO_LOC = %s", (id_veiculo_loc,))
        veiculo_info = cursor.fetchone()
        de_veiculo = veiculo_info['DE_VEICULO']
        
        # Obter email do motorista
        motorista_email = motorista_info['EMAIL']
        
        cursor.close()
        
        # Enviar e-mail para a empresa locadora (passando email_fornecedor)
        email_enviado, erro_email = enviar_email_locacao(
            id_item, id_cl, nu_sei, motorista_info['NM_MOTORISTA'], motorista_info['NU_TELEFONE'], 
            dt_inicial, dt_final, hr_inicial, de_veiculo, obs, nome_arquivo_cnh, 
            motorista_email, objetivo, email_fornecedor, file_pdf
        )
        
        response_data = {
            'sucesso': True,
            'email_enviado': email_enviado,
            'mensagem': 'Locação cadastrada com sucesso!'
        }
        
        if not email_enviado and erro_email:
            response_data['erro_email'] = erro_email
            
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Erro ao cadastrar locação: {str(e)}")
        return jsonify({
            'sucesso': False,
            'mensagem': str(e)
        }), 500


def enviar_email_locacao(id_item, id_cl, nu_sei, nm_motorista, nu_telefone, dt_inicial, dt_final, 
                         hr_inicial, de_veiculo, obs, nome_arquivo_cnh, email_mot, objetivo, 
                         email_fornecedor, file_pdf_content=None):
    try:
        # Importar pytz para timezone
        from pytz import timezone
        
        # Tratar email do fornecedor
        # Remove espaços em branco extras e divide por vírgula
        emails_lista = []
        if email_fornecedor:
            # Remove espaços extras, divide por vírgula e filtra emails vazios
            emails_lista = [email.strip() for email in email_fornecedor.split(',') if email.strip()]
        
        # Validar se temos pelo menos um email
        if not emails_lista:
            app.logger.error("Nenhum email válido encontrado para o fornecedor")
            return False, "Email do fornecedor não configurado"
        
        # String formatada para salvar no banco (com vírgulas e espaços)
        emails_string = ", ".join(emails_lista)
        
        # Obter hora atual no fuso horário de Manaus
        tz_manaus = timezone('America/Manaus')
        hora_atual = datetime.now(tz_manaus).hour
        saudacao = "Bom dia" if 5 <= hora_atual < 12 else "Boa tarde" if 12 <= hora_atual < 18 else "Boa noite"
        
        # Obter nome do usuário da sessão
        nome_usuario = session.get('usuario_nome', 'Administrador')
        
        # Formatação do assunto
        assunto = f"TJRO - Locação de Veículo {id_item} - {nm_motorista}"
        
        # Tratamento do campo nu_sei
        if nu_sei and nu_sei.strip() and nu_sei != 'None':
            texto_processo = f"Em atenção ao Processo Administrativo nº {nu_sei}, solicito locação de veículo conforme informações abaixo:"
        else:
            texto_processo = "Solicito locação de veículo conforme informações abaixo:"
        
        # Tratamento do campo telefone
        if nu_telefone and nu_telefone.strip() and nu_telefone != 'None':
            info_condutor = f"{nm_motorista} - Telefone {nu_telefone}"
        else:
            info_condutor = nm_motorista
        
        # Tratamento das observações
        if obs and obs.strip() and obs != 'None':
            obs_texto = obs
        else:
            obs_texto = "Sem observações adicionais"

        # Corpo do email em HTML
        corpo_html = f'''
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Solicitação de Locação de Veículo</title>
        </head>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
            <div style="background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <!-- Header -->
                <div style="text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 3px solid #1e3a8a;">
                    <h1 style="color: #1e3a8a; margin: 0; font-size: 20px; font-weight: bold;">
                        TRIBUNAL DE JUSTIÇA DO ESTADO DE RONDÔNIA
                    </h1>
                    <p style="color: #6b7280; margin: 5px 0 0 0; font-size: 14px;">
                        Seção de Gestão Operacional do Transporte
                    </p>
                </div>
                
                <!-- Saudação -->
                <div style="margin-bottom: 25px;">
                    <p style="font-size: 16px; margin: 0; color: #374151;">
                        <strong>{saudacao},</strong>
                    </p>
                </div>
                
                <!-- Conteúdo Principal -->
                <div style="margin-bottom: 30px;">
                    <p style="margin-bottom: 20px; color: #374151;">
                        Prezados,
                    </p>
                    <p style="margin-bottom: 25px; color: #374151;">
                        {texto_processo}
                    </p>
                </div>
                
                <!-- Informações da Locação -->
                <div style="background-color: #f8fafc; padding: 25px; border-radius: 8px; border-left: 4px solid #1e3a8a; margin-bottom: 25px;">
                    <h3 style="color: #1e3a8a; margin-top: 0; margin-bottom: 20px; font-size: 18px;">
                        📋 Detalhes da Solicitação - ID {id_item}
                    </h3>
                    
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 3px 0; font-weight: bold; color: #1e3a8a; font-size: 15px; width: 30%;">
                                🗓️ Período:
                            </td>
                            <td style="padding: 3px 0; color: #374151; font-weight: 500;">
                                {dt_inicial} ({hr_inicial}) a {dt_final}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 3px 0; font-weight: bold; color: #1e3a8a; font-size: 15px;">
                                🚗 Veículo:
                            </td>
                            <td style="padding: 3px 0; color: #374151; font-weight: 500;">
                                {de_veiculo} ou Similar
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 3px 0; font-weight: bold; color: #1e3a8a; font-size: 15px;">
                                👤 Condutor:
                            </td>
                            <td style="padding: 3px 0; color: #374151; font-weight: 500;">
                                {info_condutor}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 3px 0; font-weight: bold; color: #1e3a8a; font-size: 15px; vertical-align: top;">
                                🔂 Objetivo:
                            </td>
                            <td style="padding: 3px 0; color: #374151; font-weight: 500;">
                                {objetivo}
                            </td>							
                        </tr>
                        <tr>
                            <td style="padding: 3px 0; font-weight: bold; color: #1e3a8a; font-size: 15px; vertical-align: top;">
                                📝 Observações:
                            </td>
                            <td style="padding: 3px 0; color: #374151; font-weight: 500;">
                                {obs_texto}
                            </td>
                        </tr>
                    </table>
                </div>
                
                <!-- Anexo -->
                <div style="background-color: #ecfdf5; padding: 15px; border-radius: 8px; border-left: 4px solid #10b981; margin-bottom: 25px;">
                    <p style="margin: 0; color: #065f46; font-weight: 500;">
                        📎 Segue anexo CNH do condutor.
                    </p>
                </div>
                
                <!-- Assinatura -->
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                    <p style="margin-bottom: 15px; color: #374151;">
                        Atenciosamente,
                    </p>
                    <p style="margin-bottom: 2px; font-weight: bold; color: #1e3a8a;">
                        {nome_usuario}
                    </p>
                    <p style="margin-bottom: 2px; color: #6b7280; font-size: 14px;">
                        Tribunal de Justiça do Estado de Rondônia
                    </p>
                    <p style="margin-bottom: 2px; color: #6b7280; font-size: 14px;">
                        Seção de Gestão Operacional do Transporte
                    </p>
                    <p style="margin: 0; color: #1e3a8a; font-size: 14px; font-weight: 500;">
                        📞 (69) 3309-6229/6227
                    </p>
                </div>
	
                <!-- Footer -->
                <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                        Este e-mail foi gerado automaticamente pelo Sistema de Operações de Transporte do TJRO
                    </p>
                </div>
            </div>
        </body>
        </html>
        '''
        
        # Versão texto simples (fallback)
        corpo_texto = f'''{saudacao},

Prezados,

{texto_processo}

    Período: {dt_inicial} ({hr_inicial}) a {dt_final}
    Veículo: {de_veiculo} ou Similar
    Condutor: {info_condutor}
    Objetivo: {objetivo}
    Observações: {obs_texto}

Segue anexo CNH do condutor.

Atenciosamente,

{nome_usuario}
Tribunal de Justiça do Estado de Rondônia
Seção de Gestão Operacional do Transporte
(69) 3309-6229/6227'''

        # Criar mensagem usando a lista de emails tratada
        msg = Message(
            subject=assunto,
            recipients=emails_lista,  # Usa a lista de emails processada
            html=corpo_html,
            body=corpo_texto,
            sender=("TJRO-SEGEOP", "segeop@tjro.jus.br")
        )

        # Anexar CNH
        if file_pdf_content:
            nome_anexo = f"CNH_{nm_motorista.replace(' ', '_')}.pdf"
            if nome_arquivo_cnh:
                nome_anexo = 'CNH_' + os.path.basename(nome_arquivo_cnh)
            msg.attach(nome_anexo, 'application/pdf', file_pdf_content)
        elif nome_arquivo_cnh and nome_arquivo_cnh != 'None':
            try:
                with open(nome_arquivo_cnh, 'rb') as f:
                    msg.attach('CNH_' + os.path.basename(nome_arquivo_cnh), 'application/pdf', f.read())
            except FileNotFoundError:
                app.logger.warning(f"Arquivo CNH não encontrado: {nome_arquivo_cnh}")
        
        # Enviar email
        mail.send(msg)
        
        # Registrar email no banco de dados
        cursor = mysql.connection.cursor()
        
        # Formatação da data e hora atual no fuso de Manaus
        data_hora_atual = datetime.now(tz_manaus).strftime("%d/%m/%Y %H:%M:%S")
        
        # Inserir na tabela de emails usando a string formatada de emails
        cursor.execute(
            "INSERT INTO CONTROLE_LOCACAO_EMAIL (ID_ITEM, ID_CL, DESTINATARIO, ASSUNTO, TEXTO, DATA_HORA) VALUES (%s, %s, %s, %s, %s, %s)",
            (id_item, id_cl, emails_string, assunto, corpo_texto, data_hora_atual)
        )
        
        # Atualizar flag de email na tabela de locações
        cursor.execute(
            "UPDATE CONTROLE_LOCACAO_ITENS SET FL_EMAIL = 'S' WHERE ID_ITEM = %s",
            (id_item,)
        )
        
        mysql.connection.commit()
        cursor.close()
        
        return True, None
    
    except Exception as e:
        app.logger.error(f"Erro ao enviar email: {str(e)}")
        return False, str(e)
		
        
@app.route('/api/download_cnh_loc/<int:id_motorista>')
@login_required
def download_cnh_loc(id_motorista):
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)  # IMPORTANTE: Use dictionary=True aqui também
        cursor.execute("""
            SELECT FILE_PDF, NOME_ARQUIVO FROM CAD_MOTORISTA
            WHERE ID_MOTORISTA = %s
        """, (id_motorista,))
        
        result = cursor.fetchone()
        cursor.close()
        
        if result and result['FILE_PDF']:  # Acesso usando chave string
            pdf_data = result['FILE_PDF']
            filename = result['NOME_ARQUIVO'] or f"cnh_motorista_{id_motorista}.pdf"
            
            response = make_response(pdf_data)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'inline; filename="{filename}"'
            return response
        else:
            return jsonify({'erro': 'PDF não encontrado'}), 404
    except Exception as e:
        print(f"Erro ao baixar PDF: {str(e)}")
        return jsonify({'erro': str(e)}), 500
    
@app.route('/api/excluir_locacao/<int:iditem>', methods=['DELETE'])
@login_required
def excluir_locacao(iditem):
    try:
        # Verificar se o item existe antes de excluir
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT ID_ITEM FROM CONTROLE_LOCACAO_ITENS WHERE ID_ITEM = %s", (iditem,))
        item = cursor.fetchone()
        
        if not item:
            return jsonify({
                'sucesso': False,
                'mensagem': 'Item não encontrado'
            }), 404
        
        # Exclui os emails relacionados
        cursor.execute("""
            DELETE FROM CONTROLE_LOCACAO_EMAIL
            WHERE ID_ITEM = %s
        """, (iditem,))
        
        # Exclui a locação
        cursor.execute("""
            DELETE FROM CONTROLE_LOCACAO_ITENS
            WHERE ID_ITEM = %s
        """, (iditem,))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'sucesso': True,
            'mensagem': 'Locação excluída com sucesso'
        })
        
    except Exception as e:
        print(f"Erro ao excluir locação: {str(e)}")
        mysql.connection.rollback()
        return jsonify({
            'sucesso': False,
            'mensagem': f'Erro ao excluir locação: {str(e)}'
        }), 500
        
@app.route('/api/locacao_item/<int:iditem>')
@login_required
def locacao_item(iditem):
    try:
        print(f"Iniciando consulta à Locação Item para ID: {iditem}")
        cursor = mysql.connection.cursor()
        
        print("Executando consulta SQL")
        cursor.execute("""
            SELECT i.ID_EXERCICIO, i.ID_MES, i.SETOR_SOLICITANTE, i.OBJETIVO, i.ID_EMPENHO, 
            i.ID_VEICULO_LOC, i.ID_MOTORISTA, m.NM_MOTORISTA, i.QT_DIARIA_KM, i.VL_DK, 
            i.VL_SUBTOTAL, i.VL_DIFERENCA, i.VL_TOTALITEM, i.NU_SEI, i.DATA_INICIO, i.DATA_FIM, 
            i.HORA_INICIO, i.HORA_FIM, i.DS_VEICULO_MOD, i.COMBUSTIVEL, i.OBS
            FROM CONTROLE_LOCACAO_ITENS i, CAD_MOTORISTA m
            WHERE m.ID_MOTORISTA = i.ID_MOTORISTA
            AND i.ID_ITEM = %s
        """, (iditem,))
        result = cursor.fetchone()
        cursor.close()
        print(f"Dados: {result}")
        
        if result:
            print("Processando resultado...")
            import datetime  # Certifique-se que está importado
            
            # Debug para cada campo antes da conversão
            print(f"Tipos de dados dos campos:")
            print(f"dt_inicio: {type(result[14])}, valor: {result[14]}")
            print(f"dt_fim: {type(result[15])}, valor: {result[15]}")
            print(f"hora_inicio: {type(result[16])}, valor: {result[16]}")
            print(f"hora_fim: {type(result[17])}, valor: {result[17]}")
            
            try:
                # Converter datas para string
                print("Convertendo datas...")
                dt_inicio = result[14].strftime('%Y-%m-%d') if result[14] and hasattr(result[14], 'strftime') else result[14]
                dt_fim = result[15].strftime('%Y-%m-%d') if result[15] and hasattr(result[15], 'strftime') else result[15]
                print(f"Datas convertidas: {dt_inicio}, {dt_fim}")
                
                # Converter tempos
                print("Convertendo tempos...")
                def format_timedelta(td):
                    print(f"Formatando timedelta: {td}, tipo: {type(td)}")
                    if td is None:
                        return None
                    if isinstance(td, datetime.timedelta):
                        seconds = td.total_seconds()
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                    if hasattr(td, 'strftime'):
                        return td.strftime('%H:%M:%S')
                    return str(td)
                
                hora_inicio = format_timedelta(result[16])
                hora_fim = format_timedelta(result[17])
                print(f"Tempos convertidos: {hora_inicio}, {hora_fim}")
                
                # Converter valores decimais
                print("Convertendo valores...")
                valor_diaria = float(result[9]) if result[9] is not None else None
                valor_subtotal = float(result[10]) if result[10] is not None else None
                valor_diferenca = float(result[11]) if result[11] is not None else None
                valor_total = float(result[12]) if result[12] is not None else None
                print("Valores convertidos com sucesso")
                
                itens = {
                    'id_exercicio': result[0],
                    'id_mes': result[1],
                    'setor_solicitante': result[2],
                    'objetivo': result[3],
                    'id_empenho': result[4],
                    'id_veiculo_loc': result[5],
                    'id_motorista': result[6],
                    'nome_motorista': result[7],
                    'qt_diarias': float(result[8]) if result[8] is not None else None,
                    'valor_diaria': valor_diaria,
                    'valor_subtotal': valor_subtotal,
                    'valor_diferenca': valor_diferenca,
                    'valor_total': valor_total,
                    'nu_sei': result[13],
                    'dt_inicio': dt_inicio,
                    'dt_fim': dt_fim,
                    'hora_inicio': hora_inicio,
                    'hora_fim': hora_fim,
                    'veiculo_modelo': result[18],
                    'combustivel': result[19],
		    'obs': result[20]
                }
                print("Dicionário itens criado com sucesso")
                
                # Debug - veja o que está sendo enviado
                print("Enviando para o frontend:", itens)
                return jsonify(itens)
            
            except Exception as e:
                print(f"Erro durante processamento dos dados: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'erro': f"Erro ao processar dados: {str(e)}"}), 500
        else:
            print(f"Locação com ID {iditem} não encontrada")
            return jsonify({'erro': 'Locação não encontrada'}), 400
    except Exception as e:
        return jsonify({'erro': str(e)}), 500  
        
@app.route('/api/busca_modelos_veiculos')
@login_required
def busca_modelos_veiculos():
    try:
        termo = request.args.get('termo', '')
        if len(termo) < 3:
            return jsonify([])
            
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT DS_VEICULO_MOD 
            FROM CONTROLE_LOCACAO_ITENS
            WHERE DS_VEICULO_MOD LIKE %s
            LIMIT 10
        """, (f'%{termo}%',))
        
        result = cursor.fetchall()
        cursor.close()
        
        modelos = [row[0] for row in result]
        return jsonify(modelos)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/busca_combustivel')
@login_required
def busca_combustivel():
    try:
        termo = request.args.get('termo', '')
            
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT COMBUSTIVEL FROM CONTROLE_LOCACAO_ITENS
            WHERE DS_VEICULO_MOD = %s
        """, (termo,))
                
        result = cursor.fetchall()
        cursor.close()
        
        combustivel = [row[0] for row in result]
        return jsonify(combustivel)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/salvar_devolucao/<int:iditem>', methods=['POST'])
@login_required
def salvar_devolucao(iditem):
    try:
        data = request.form
        data_inicio = data.get('data_inicio')
        data_fim = data.get('data_fim')
        hora_inicio = data.get('hora_inicio')
        hora_fim = data.get('hora_fim')
        qt_diarias = data.get('qt_diarias')
        km_rodado = data.get('km_rodado')
        
        #qt_diarias = float(data.get('qt_diarias', 0))
        # Converter data_inicio e data_fim para objetos datetime
        data_inicio_obj = datetime.strptime(data_inicio, '%Y-%m-%d')
        data_fim_obj = datetime.strptime(data_fim, '%Y-%m-%d')
        
        # Extrair ano e mês da data de fim
        id_exercicio = data_fim_obj.year
        id_mes = data_fim_obj.month
        
        # Converter data para o formato dd/mm/yyyy para os campos de string
        dt_inicial = data_inicio_obj.strftime('%d/%m/%Y')
        dt_final = data_fim_obj.strftime('%d/%m/%Y')
        
        # Converter hora para string no formato hh:mm
        hr_inicial = hora_inicio
        hr_final = hora_fim
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE CONTROLE_LOCACAO_ITENS SET
            OBJETIVO = %s,
            SETOR_SOLICITANTE = %s,
            ID_VEICULO_LOC = %s,
            ID_MOTORISTA = %s,
            ID_EXERCICIO = %s,
            ID_MES = %s,
            DATA_INICIO = %s,
            DATA_FIM = %s,
            HORA_INICIO = %s,
            HORA_FIM = %s,
            DT_INICIAL = %s,
            DT_FINAL = %s,
            HR_INICIAL = %s,
            HR_FINAL = %s,
            QT_DIARIA_KM = %s,
            VL_DIFERENCA = %s,
            VL_SUBTOTAL = %s,
            VL_TOTALITEM = %s,
            DS_VEICULO_MOD = %s,
            FL_STATUS = 'F',
            KM_RODADO = %s,
            COMBUSTIVEL = %s,
            OBS_DEV = %s
            WHERE ID_ITEM = %s
        """, (
            data.get('objetivo'),
            data.get('setor_solicitante'),
            data.get('id_veiculo'),
            data.get('id_motorista'),
            id_exercicio, id_mes,
            data.get('data_inicio'),
            data.get('data_fim'),
            data.get('hora_inicio'),
            data.get('hora_fim'),
            dt_inicial, dt_final, hr_inicial, hr_final,
            qt_diarias,
            data.get('valor_diferenca'),
            data.get('valor_subtotal'),
            data.get('valor_total'),
            data.get('veiculo_modelo'),
            km_rodado,
            data.get('combustivel'),
            data.get('obs_dev'),
            iditem
        ))
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'mensagem': 'Devolução registrada com sucesso!'})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/editar_locacao/<int:iditem>', methods=['POST'])
@login_required
def editar_locacao(iditem):
    try:
        data = request.form
        data_inicio = data.get('data_inicio')
        data_fim = data.get('data_fim')
        hora_inicio = data.get('hora_inicio')
        hora_fim = data.get('hora_fim')
        qt_diarias = data.get('qt_diarias')
        km_rodado = data.get('km_rodado')
        
        #qt_diarias = float(data.get('qt_diarias', 0))
        # Converter data_inicio e data_fim para objetos datetime
        data_inicio_obj = datetime.strptime(data_inicio, '%Y-%m-%d')
        data_fim_obj = datetime.strptime(data_fim, '%Y-%m-%d')
        
        # Extrair ano e mês da data de fim
        id_exercicio = data_fim_obj.year
        id_mes = data_fim_obj.month
        
        # Converter data para o formato dd/mm/yyyy para os campos de string
        dt_inicial = data_inicio_obj.strftime('%d/%m/%Y')
        dt_final = data_fim_obj.strftime('%d/%m/%Y')
        
        # Converter hora para string no formato hh:mm
        hr_inicial = hora_inicio
        hr_final = hora_fim
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE CONTROLE_LOCACAO_ITENS SET
            OBJETIVO = %s,
            SETOR_SOLICITANTE = %s,
            ID_VEICULO_LOC = %s,
            ID_MOTORISTA = %s,
            ID_EXERCICIO = %s,
            ID_MES = %s,
            DATA_INICIO = %s,
            DATA_FIM = %s,
            HORA_INICIO = %s,
            HORA_FIM = %s,
            DT_INICIAL = %s,
            DT_FINAL = %s,
            HR_INICIAL = %s,
            HR_FINAL = %s,
            QT_DIARIA_KM = %s,
            VL_DIFERENCA = %s,
            VL_SUBTOTAL = %s,
            VL_TOTALITEM = %s,
            DS_VEICULO_MOD = %s,
            COMBUSTIVEL = %s,
            OBS = %s
            WHERE ID_ITEM = %s
        """, (
            data.get('objetivo'),
            data.get('setor_solicitante'),
            data.get('id_veiculo'),
            data.get('id_motorista'),
            id_exercicio, id_mes,
            data.get('data_inicio'),
            data.get('data_fim'),
            data.get('hora_inicio'),
            data.get('hora_fim'),
            dt_inicial, dt_final, hr_inicial, hr_final,
            qt_diarias,
            data.get('valor_diferenca'),
            data.get('valor_subtotal'),
            data.get('valor_total'),
            data.get('veiculo_modelo'),
            data.get('combustivel'),
            data.get('obs'),
            iditem
        ))
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'mensagem': 'Alteração registrada com sucesso!'})
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/locacao_visualiza/<int:iditem>')
@login_required
def locacao_visualiza(iditem):
    try:
        print(f"Iniciando consulta à Locação Item para ID: {iditem}")
        cursor = mysql.connection.cursor()
        
        print("Executando consulta SQL")
        cursor.execute("""
			SELECT e.NU_EMPENHO, i.SETOR_SOLICITANTE, i.OBJETIVO, i.NU_SEI, m.NM_MOTORISTA, 
            v.DE_VEICULO, i.DS_VEICULO_MOD, i.COMBUSTIVEL, i.DATA_INICIO, i.DATA_FIM, 
            i.HORA_INICIO, i.HORA_FIM, i.QT_DIARIA_KM, i.VL_DK, 
            i.VL_SUBTOTAL, i.VL_DIFERENCA, i.VL_TOTALITEM, i.KM_RODADO, i.OBS, i.OBS_DEV
            FROM CONTROLE_LOCACAO_ITENS i, CAD_MOTORISTA m, 
            CONTROLE_LOCACAO_EMPENHOS e, CAD_VEICULOS_LOCACAO v
            WHERE v.ID_VEICULO_LOC = i.ID_VEICULO_LOC 
            AND e.ID_EMPENHO = i.ID_EMPENHO 
            AND m.ID_MOTORISTA = i.ID_MOTORISTA
            AND i.ID_ITEM = %s
        """, (iditem,))
        result = cursor.fetchone()
        cursor.close()
        print(f"Dados: {result}")
        
        if result:
            print("Processando resultado...")
            import datetime  # Certifique-se que está importado
            
            # Debug para cada campo antes da conversão
            print(f"Tipos de dados dos campos:")
            print(f"dt_inicio: {type(result[8])}, valor: {result[8]}")
            print(f"dt_fim: {type(result[9])}, valor: {result[9]}")
            print(f"hora_inicio: {type(result[10])}, valor: {result[10]}")
            print(f"hora_fim: {type(result[11])}, valor: {result[11]}")
            
            try:
                # Converter datas para string
                print("Convertendo datas...")
                dt_inicio = result[8].strftime('%Y-%m-%d') if result[8] and hasattr(result[8], 'strftime') else result[8]
                dt_fim = result[9].strftime('%Y-%m-%d') if result[9] and hasattr(result[9], 'strftime') else result[9]
                print(f"Datas convertidas: {dt_inicio}, {dt_fim}")
                
                # Converter tempos
                print("Convertendo tempos...")
                def format_timedelta(td):
                    print(f"Formatando timedelta: {td}, tipo: {type(td)}")
                    if td is None:
                        return None
                    if isinstance(td, datetime.timedelta):
                        seconds = td.total_seconds()
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                    if hasattr(td, 'strftime'):
                        return td.strftime('%H:%M:%S')
                    return str(td)
                
                hora_inicio = format_timedelta(result[10])
                hora_fim = format_timedelta(result[11])
                print(f"Tempos convertidos: {hora_inicio}, {hora_fim}")
                
                # Converter valores decimais
                print("Convertendo valores...")
                valor_diaria = float(result[13]) if result[13] is not None else None
                valor_subtotal = float(result[14]) if result[14] is not None else None
                valor_diferenca = float(result[15]) if result[15] is not None else None
                valor_total = float(result[16]) if result[16] is not None else None
                print("Valores convertidos com sucesso")
                
                itens = {
                    'nu_empenho': result[0],
                    'setor_solicitante': result[1],
                    'objetivo': result[2],
                    'nu_sei': result[3],
                    'nome_motorista': result[4],
                    'de_veiculo': result[5],
                    'veiculo_modelo': result[6],
                    'combustivel': result[7],
                    'dt_inicio': dt_inicio,
                    'dt_fim': dt_fim,
                    'hora_inicio': hora_inicio,
                    'hora_fim': hora_fim,
                    'qt_diarias': float(result[12]) if result[12] is not None else None,
                    'valor_diaria': valor_diaria,
                    'valor_subtotal': valor_subtotal,
                    'valor_diferenca': valor_diferenca,
                    'valor_total': valor_total,
                    'km_rodado': result[17],
                    'obs': result[18],
                    'obs_dev': result[19]
                }
                print("Dicionário itens criado com sucesso")
                
                # Debug - veja o que está sendo enviado
                print("Enviando para o frontend:", itens)
                return jsonify(itens)
            
            except Exception as e:
                print(f"Erro durante processamento dos dados: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'erro': f"Erro ao processar dados: {str(e)}"}), 500
        else:
            print(f"Locação com ID {iditem} não encontrada")
            return jsonify({'erro': 'Locação não encontrada'}), 400
    except Exception as e:
        return jsonify({'erro': str(e)}), 500    
        
@app.route('/fluxo_veiculos')
@login_required
def fluxo_veiculos():
    return render_template('fluxo_veiculos.html')
        
@app.route('/api/fluxo_busca_setor')
@login_required
def fluxo_busca_setor():
    try:
        termo = request.args.get('termo', '')
        if len(termo) < 3:
            return jsonify([])
            
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT SETOR_SOLICITANTE 
            FROM FLUXO_VEICULOS
            WHERE SETOR_SOLICITANTE LIKE %s
            ORDER BY SETOR_SOLICITANTE
        """, (f'%{termo}%',))
        
        result = cursor.fetchall()
        cursor.close()
        
        setores = [row[0] for row in result]
        return jsonify(setores)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500   
        
@app.route('/api/fluxo_busca_destino')
@login_required
def fluxo_busca_destino():
    try:
        termo = request.args.get('termo', '')
        if len(termo) < 3:
            return jsonify([])
            
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT DESTINO 
            FROM FLUXO_VEICULOS
            WHERE DESTINO LIKE %s
            ORDER BY DESTINO
        """, (f'%{termo}%',))
        
        result = cursor.fetchall()
        cursor.close()
        
        destinos = [row[0] for row in result]
        return jsonify(destinos)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500    
        
@app.route('/api/fluxo_lista_motorista')
@login_required
def fluxo_lista_motorista():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
        SELECT ID_MOTORISTA, NM_MOTORISTA 
        FROM CAD_MOTORISTA WHERE ATIVO = 'S' AND ID_MOTORISTA <> 0
        ORDER BY NM_MOTORISTA
        """)
               
        items = cursor.fetchall()
        motoristas = []
        for item in items:
            lista = {'ID_MOTORISTA': item[0],
                     'NM_MOTORISTA': item[1]}
            motoristas.append(lista)
            
        cursor.close()
        return jsonify(motoristas)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar setores: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/api/fluxo_lista_veiculos')
@login_required
def fluxo_lista_veiculos():
    try:
        # SELECT ID_VEICULO, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO 
        # FROM CAD_VEICULOS WHERE FL_ATENDIMENTO = 'S'
        # ORDER BY DS_MODELO
  
        cursor = mysql.connection.cursor()
        cursor.execute("""
        SELECT v.ID_VEICULO, CONCAT(v.DS_MODELO,' - ',v.NU_PLACA) AS VEICULO 
        FROM CAD_VEICULOS v 
        WHERE v.ID_VEICULO NOT IN 
            (SELECT ID_VEICULO FROM FLUXO_VEICULOS
			 WHERE FL_STATUS = 'S') 
        AND v.FL_ATENDIMENTO = 'S'
        ORDER BY v.DS_MODELO 
        """)
               
        items = cursor.fetchall()
        veiculos = []
        for item in items:
            lista = {'ID_VEICULO': item[0],
                     'VEICULO': item[1]}
            veiculos.append(lista)
            
        cursor.close()
        return jsonify(veiculos)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar setores: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
@app.route('/api/fluxo_veiculo_saida_sem_retorno')
@login_required
def fluxo_veiculo_saida_sem_retorno():
    try:
        cursor = mysql.connection.cursor()
        
        print("Executando consulta SQL")
        cursor.execute("""
            SELECT f.ID_FLUXO, f.SETOR_SOLICITANTE, f.DESTINO,
                CONCAT(v.NU_PLACA,' - ',v.DS_MODELO) AS VEICULO, 
                f.ID_VEICULO, f.ID_MOTORISTA, 
                CASE WHEN f.ID_MOTORISTA=0 THEN 
                CONCAT('*',f.NC_CONDUTOR) ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA, 
                CONCAT(f.DT_SAIDA,' ',f.HR_SAIDA) AS SAIDA, f.OBS
            FROM FLUXO_VEICULOS f
            INNER JOIN CAD_VEICULOS v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN CAD_MOTORISTA m 
                ON f.ID_MOTORISTA = m.ID_MOTORISTA
            WHERE f.DATA_RETORNO IS NULL
            AND f.DATA_SAIDA = CURDATE()
            ORDER BY f.DATA_SAIDA, f.HORA_SAIDA
        """)
        results = cursor.fetchall()  # Altere para fetchall() para obter todos os registros
        cursor.close()
        print(f"Número de registros encontrados: {len(results)}")
        
        if results:
            print("Processando resultados...")
            itens_list = []
            
            try:
                for result in results:
                    item = {
                        'id_fluxo': result[0],
                        'setor_solicitante': result[1],
                        'destino': result[2],
                        'veiculo': result[3],
                        'id_veiculo': result[4],''
                        'id_motorista': result[5],
                        'nome_motorista': result[6],
                        'datahora_saida': result[7],
                        'obs': result[8]
                    }
                    itens_list.append(item)
                
                print(f"Lista de itens criada com sucesso. Total: {len(itens_list)}")
                # Debug - veja o que está sendo enviado
                print("Enviando para o frontend:", itens_list)
                return jsonify(itens_list)  # Retorne a lista completa
            
            except Exception as e:
                print(f"Erro durante processamento dos dados: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'erro': f"Erro ao processar dados: {str(e)}"}), 500
        else:
            return jsonify([])  # Retorne lista vazia em vez de erro quando não houver dados
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/fluxo_veiculo_retorno_dia')
@login_required
def fluxo_veiculo_retorno_dia():
    try:
        cursor = mysql.connection.cursor()
        
        print("Executando consulta SQL")
        cursor.execute("""
            SELECT f.ID_FLUXO, f.SETOR_SOLICITANTE, f.DESTINO,
                CONCAT(v.NU_PLACA,' - ',v.DS_MODELO) AS VEICULO, 
                f.ID_VEICULO, f.ID_MOTORISTA, 
                CASE WHEN f.ID_MOTORISTA=0 THEN 
                CONCAT('*',f.NC_CONDUTOR) ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA, 
                CONCAT(f.DT_SAIDA,' ',f.HR_SAIDA) AS SAIDA, 
                CONCAT(f.DT_RETORNO,' ',f.HR_RETORNO) AS RETORNO, f.OBS_RETORNO
            FROM FLUXO_VEICULOS f
            INNER JOIN CAD_VEICULOS v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN CAD_MOTORISTA m 
                ON f.ID_MOTORISTA = m.ID_MOTORISTA
            WHERE f.DATA_RETORNO IS NOT NULL
            AND f.DATA_RETORNO = CURDATE()
            ORDER BY f.DATA_RETORNO, f.HORA_RETORNO
        """)
        results = cursor.fetchall()  # Altere para fetchall()
        cursor.close()
        print(f"Número de registros encontrados: {len(results)}")
        
        if results:
            print("Processando resultados...")
            itens_list = []
            
            try:
                for result in results:
                    item = {
                        'id_fluxo': result[0],
                        'setor_solicitante': result[1],
                        'destino': result[2],
                        'veiculo': result[3],
                        'id_veiculo': result[4],
                        'id_motorista': result[5],
                        'nome_motorista': result[6],
                        'datahora_saida': result[7],
                        'datahora_retorno': result[8],
                        'obs': result[9]
                    }
                    itens_list.append(item)
                
                print(f"Lista de itens criada com sucesso. Total: {len(itens_list)}")
                return jsonify(itens_list)  # Retorne a lista completa
            
            except Exception as e:
                print(f"Erro durante processamento dos dados: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'erro': f"Erro ao processar dados: {str(e)}"}), 500
        else:
            return jsonify([])  # Retorne lista vazia
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/fluxo_veiculo_saida_retorno_pendente')
@login_required
def fluxo_veiculo_saida_retorno_pendente():
    try:
        cursor = mysql.connection.cursor()
        
        print("Executando consulta SQL")
        cursor.execute("""
            SELECT f.ID_FLUXO, f.SETOR_SOLICITANTE, f.DESTINO,
                CONCAT(v.NU_PLACA,' - ',v.DS_MODELO) AS VEICULO, 
                f.ID_VEICULO, f.ID_MOTORISTA, 
                CASE WHEN f.ID_MOTORISTA=0 THEN 
                CONCAT('*',f.NC_CONDUTOR) ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA, 
                CONCAT(f.DT_SAIDA,' ',f.HR_SAIDA) AS SAIDA, f.OBS
            FROM FLUXO_VEICULOS f
            INNER JOIN CAD_VEICULOS v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN CAD_MOTORISTA m 
                ON f.ID_MOTORISTA = m.ID_MOTORISTA
            WHERE f.DATA_RETORNO IS NULL
            AND f.DATA_SAIDA <> CURDATE()
            ORDER BY f.DATA_SAIDA, f.HORA_SAIDA
        """)
        results = cursor.fetchall()  # Altere para fetchall()
        cursor.close()
        print(f"Número de registros encontrados: {len(results)}")
        
        if results:
            print("Processando resultados...")
            itens_list = []
            
            try:
                for result in results:
                    item = {
                        'id_fluxo': result[0],
                        'setor_solicitante': result[1],
                        'destino': result[2],
                        'veiculo': result[3],
                        'id_veiculo': result[4],
                        'id_motorista': result[5],
                        'nome_motorista': result[6],
                        'datahora_saida': result[7],
                        'obs': result[8]
                    }
                    itens_list.append(item)
                
                print(f"Lista de itens criada com sucesso. Total: {len(itens_list)}")
                return jsonify(itens_list)  # Retorne a lista completa
            
            except Exception as e:
                print(f"Erro durante processamento dos dados: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'erro': f"Erro ao processar dados: {str(e)}"}), 500
        else:
            return jsonify([])  # Retorne lista vazia
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/api/fluxo_saida_item/<int:idfluxo>')
@login_required
def fluxo_saida_item(idfluxo):
    try:
        print(f"Iniciando consulta à Saida para ID: {idfluxo}")
        cursor = mysql.connection.cursor()
        
        print("Executando consulta SQL")
        cursor.execute("""
            SELECT f.ID_FLUXO, f.SETOR_SOLICITANTE, f.DESTINO,
                f.ID_VEICULO, f.ID_MOTORISTA, f.DATA_SAIDA, f.HORA_SAIDA, 
                f.DATA_RETORNO, f.HORA_RETORNO, f.OBS,
                CONCAT(v.NU_PLACA,' - ',v.DS_MODELO) AS VEICULO,  
                CASE WHEN f.ID_MOTORISTA=0 THEN 
                CONCAT('*',f.NC_CONDUTOR) ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA
            FROM FLUXO_VEICULOS f
            INNER JOIN CAD_VEICULOS v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN CAD_MOTORISTA m 
                ON f.ID_MOTORISTA = m.ID_MOTORISTA
            WHERE f.ID_FLUXO = %s
        """, (idfluxo,))
        result = cursor.fetchone()
        cursor.close()
        print(f"Dados: {result}")
        
        if result:
            print("Processando resultado...")
            import datetime  # Certifique-se que está importado
            
            # Debug para cada campo antes da conversão
            print(f"Tipos de dados dos campos:")
            print(f"dt_saida: {type(result[5])}, valor: {result[5]}")
            print(f"dt_retorno: {type(result[7])}, valor: {result[7]}")
            print(f"hora_saida: {type(result[6])}, valor: {result[6]}")
            print(f"hora_retorno: {type(result[8])}, valor: {result[8]}")
            
            try:
                # Converter datas para string
                print("Convertendo datas...")
                dt_saida = result[5].strftime('%Y-%m-%d') if result[5] and hasattr(result[5], 'strftime') else result[5]
                dt_retorno = result[7].strftime('%Y-%m-%d') if result[7] and hasattr(result[7], 'strftime') else result[7]
                print(f"Datas convertidas: {dt_saida}, {dt_retorno}")
                
                # Converter tempos
                print("Convertendo tempos...")
                def format_timedelta(td):
                    print(f"Formatando timedelta: {td}, tipo: {type(td)}")
                    if td is None:
                        return None
                    if isinstance(td, datetime.timedelta):
                        seconds = td.total_seconds()
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        secs = int(seconds % 60)
                        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
                    if hasattr(td, 'strftime'):
                        return td.strftime('%H:%M:%S')
                    return str(td)
                
                hora_saida = format_timedelta(result[6])
                hora_retorno = format_timedelta(result[8])       
                
                itens = {
                    'id_fluxo': result[0],
                    'setor_solicitante': result[1],
                    'destino': result[2],
                    'id_veiculo': result[3],
                    'veiculo': result[10],
                    'id_motorista': result[4],
                    'nome_motorista': result[11],
                    'dt_saida': dt_saida,
                    'dt_retorno': dt_retorno,
                    'hora_saida': hora_saida,
                    'hora_retorno': hora_retorno,
		            'obs': result[9]
                }
                print("Dicionário itens criado com sucesso")
                
                # Debug - veja o que está sendo enviado
                print("Enviando para o frontend:", itens)
                return jsonify(itens)
            
            except Exception as e:
                print(f"Erro durante processamento dos dados: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'erro': f"Erro ao processar dados: {str(e)}"}), 500
        else:
            print(f"Locação com ID {idfluxo} não encontrada")
            return jsonify({'erro': 'Locação não encontrada'}), 400
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
# Rota para obter o próximo ID_ITEM
def obter_proximo_id_fluxo():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT MAX(ID_FLUXO) FROM FLUXO_VEICULOS")
    resultado = cursor.fetchone()
    cursor.close()
    
    ultimo_id = resultado[0] if resultado[0] else 0
    return ultimo_id + 1
    
@app.route('/api/fluxo_nova_saida', methods=['POST'])
@login_required
def fluxo_nova_saida():
    try:
        setor_solicitante = request.form.get('setorSolicitante_saida')
        destino = request.form.get('destino_saida')
        id_veiculo = request.form.get('veiculo_saida')
        id_motorista = request.form.get('motorista_saida')
        motorista_nc = request.form.get('motoristanaocad_saida')
        data_saida = request.form.get('datasaida_saida')
        hora_saida = request.form.get('horasaida_saida')
        obs_saida = request.form.get('obs_saida')
        
        # Obter o próximo ID_ITEM
        id_fluxo = obter_proximo_id_fluxo()
        
        # Converter data_inicio e data_fim para objetos datetime
        data_saida_obj = datetime.strptime(data_saida, '%Y-%m-%d')
        
        # Converter data para o formato dd/mm/yyyy para os campos de string
        dt_saida = data_saida_obj.strftime('%d/%m/%Y')
        
        # Converter hora para string no formato hh:mm
        hr_saida = hora_saida
        
        # Obter ID do usuário da sessão
        usuario = session.get('usuario_login')
        cursor = mysql.connection.cursor() 
        # Inserir na tabela FLUXO_VEICULOS
        cursor.execute("""
            INSERT INTO FLUXO_VEICULOS (
                ID_FLUXO, ID_VEICULO, DT_SAIDA, HR_SAIDA, SETOR_SOLICITANTE, DESTINO, 
                ID_MOTORISTA, NC_CONDUTOR, OBS, FL_STATUS, USUARIO_SAIDA, DATA_SAIDA, HORA_SAIDA
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_fluxo, id_veiculo, dt_saida, hr_saida, setor_solicitante, destino, 
              id_motorista, motorista_nc, obs_saida, 'S', usuario, data_saida, hora_saida        
        ))
        mysql.connection.commit()
              
        response_data = {
            'sucesso': True,
            'mensagem': 'Saida registrada com sucesso!'
        }
             
        cursor.close()
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Erro ao : {str(e)}")
        return jsonify({
            'sucesso': False,
            'mensagem': str(e)
        }), 500
        
@app.route('/api/fluxo_lanca_retorno/<int:idfluxo>', methods=['POST'])
@login_required
def fluxo_lanca_retorno(idfluxo):
    try:
        data_retorno = request.form.get('data_retorno')
        hora_retorno = request.form.get('hora_retorno')
        obs_retorno = request.form.get('obs_retorno')
        
        # Converter data_inicio e data_fim para objetos datetime
        data_retorno_obj = datetime.strptime(data_retorno, '%Y-%m-%d')
        
        # Converter data para o formato dd/mm/yyyy para os campos de string
        dt_retorno = data_retorno_obj.strftime('%d/%m/%Y')
        
        # Converter hora para string no formato hh:mm
        hr_retorno = hora_retorno
        
        # Obter ID do usuário da sessão
        usuario = session.get('usuario_login')
        cursor = mysql.connection.cursor() 
        # Inserir na tabela FLUXO_VEICULOS
        cursor.execute("""
            UPDATE FLUXO_VEICULOS SET
                DT_RETORNO = %s,
                HR_RETORNO = %s,
                DATA_RETORNO = %s,
                HORA_RETORNO = %s,
                FL_STATUS = %s,
                USUARIO_CHEGADA = %s,
                OBS_RETORNO = %s
            WHERE ID_FLUXO = %s
        """, (dt_retorno, hr_retorno, data_retorno, hora_retorno, 
              'R', usuario, obs_retorno, idfluxo        
        ))
        mysql.connection.commit()
              
        response_data = {
            'sucesso': True,
            'mensagem': 'Retorno registrado com sucesso!'
        }
             
        cursor.close()
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Erro ao : {str(e)}")
        return jsonify({
            'sucesso': False,
            'mensagem': str(e)
        }), 500
        
@app.route('/api/busca_motorista')
@login_required
def busca_motorista():
    try:
        nome = request.args.get('nome', '')
        cursor = mysql.connection.cursor()
        
        if nome:
            query = """
            SELECT ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, SIGLA_SETOR
            FROM CAD_MOTORISTA 
            WHERE ID_MOTORISTA > 0 AND ATIVO = 'S'
            AND CONCAT(CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, SIGLA_SETOR) LIKE %s 
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query, (f'%{nome}%',))
        else:
            query = """
            SELECT ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, SIGLA_SETOR
            FROM CAD_MOTORISTA
            WHERE ID_MOTORISTA > 0 AND ATIVO = 'S'
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query)
        
        columns = ['id_motorista', 'matricula', 'nm_motorista', 'sigla_setor']
        motoristas = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        return jsonify(motoristas)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
        
@app.route('/veiculos_frota')
@login_required
@verificar_permissao('/veiculos_frota', 'E')
def veiculos_frota():
    # Passa o nível de acesso para o template
    nivel_acesso = session.get('nivel_acesso_atual', 'L')
    return render_template('veiculos_frota.html', nivel_acesso=nivel_acesso)
	
@app.route('/api/veiculos', methods=['GET'])
@login_required
def lista_veiculos():
    try:
        filtro = request.args.get('filtro', '')
        
        cursor = mysql.connection.cursor()
        
        if filtro:
            # Busca pelo modelo ou placa
            query = """
            SELECT v.*, c.DS_CAT_VEICULO 
            FROM CAD_VEICULOS v
            LEFT JOIN CATEGORIA_VEICULO c ON v.ID_CATEGORIA = c.ID_CAT_VEICULO
            WHERE v.NU_PLACA LIKE %s OR v.DS_MODELO LIKE %s OR v.MARCA LIKE %s
            ORDER BY v.ID_VEICULO DESC
            """
            cursor.execute(query, (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'))
        else:
            # Busca todos
            query = """
            SELECT v.*, c.DS_CAT_VEICULO 
            FROM CAD_VEICULOS v
            LEFT JOIN CATEGORIA_VEICULO c ON v.ID_CATEGORIA = c.ID_CAT_VEICULO
            ORDER BY v.ID_VEICULO DESC
            """
            cursor.execute(query)
        
        veiculos = []
        columns = [column[0] for column in cursor.description]
        
        for row in cursor.fetchall():
            veiculo = {}
            for i, col in enumerate(columns):
                veiculo[col.lower()] = row[i]
            veiculos.append(veiculo)
        
        cursor.close()
        return jsonify(veiculos)
    
    except Exception as e:
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500
        
@app.route('/api/obter_veiculo/<int:id>', methods=['GET'])
@login_required
def obter_veiculo(id):
    try:
        cursor = mysql.connection.cursor()
        
        query = """
        SELECT v.*, c.DS_CAT_VEICULO 
        FROM CAD_VEICULOS v
        LEFT JOIN CATEGORIA_VEICULO c ON v.ID_CATEGORIA = c.ID_CAT_VEICULO
        WHERE v.ID_VEICULO = %s
        """
        cursor.execute(query, (id,))
        
        row = cursor.fetchone()
        
        if not row:
            return jsonify({"erro": "Veículo não encontrado"}), 404
        
        columns = [column[0] for column in cursor.description]
        veiculo = {}
        for i, col in enumerate(columns):
            veiculo[col.lower()] = row[i]
        
        cursor.close()
        return jsonify(veiculo)
    
    except Exception as e:
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500
    
@app.route('/api/veiculos/cadastrar', methods=['POST'])
@login_required
def cadastrar_veiculo():
    try:
        cursor = mysql.connection.cursor()
        
        # Get last ID and increment
        cursor.execute("SELECT COALESCE(MAX(ID_VEICULO), 0) + 1 FROM CAD_VEICULOS")
        novo_id = cursor.fetchone()[0]
        
        # Form data - CORRIGIDO: usar request.json consistentemente
        nu_placa = request.json.get('nu_placa', '').upper()
        id_categoria = request.json.get('id_categoria')
        marca = request.json.get('marca', '')
        ds_modelo = request.json.get('ds_modelo', '')
        ano_fabmod = request.json.get('ano_fabmod', '')
        origem_veiculo = request.json.get('origem_veiculo', '')
        propriedade = request.json.get('propriedade', '')
        combustivel = request.json.get('combustivel', '')
        obs = request.json.get('obs', '')
        ativo = request.json.get('ativo', 'S')
        fl_atendimento = request.json.get('fl_atendimento', 'N')
        usuario = session.get('usuario_id')
        dt_inicio = request.json.get('dt_inicio')  # CORRIGIDO
        dt_fim = request.json.get('dt_fim', None)  # CORRIGIDO

        # Get current timestamp in Manaus timezone
        manaus_tz = timezone('America/Manaus')
        dt_transacao = datetime.now(manaus_tz).strftime('%d/%m/%Y %H:%M:%S')

        # Convert DT_INICIO from DD/MM/YYYY to YYYY-MM-DD
        if dt_inicio:
            dia, mes, ano = dt_inicio.split('/')
            dt_inicio_db = f"{ano}-{mes}-{dia}"
        else:
            dt_inicio_db = None
        
        # Convert DT_FIM from DD/MM/YYYY to YYYY-MM-DD if provided
        dt_fim_db = None
        if dt_fim:
            dia, mes, ano = dt_fim.split('/')
            dt_fim_db = f"{ano}-{mes}-{dia}"

        # Insert query
        query = """
        INSERT INTO CAD_VEICULOS (
            ID_VEICULO, NU_PLACA, ID_CATEGORIA, MARCA, DS_MODELO, 
            ANO_FABMOD, ORIGEM_VEICULO, PROPRIEDADE, COMBUSTIVEL, 
            OBS, ATIVO, FL_ATENDIMENTO, USUARIO, DT_TRANSACAO, DT_INICIO, DT_FIM
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            novo_id, nu_placa, id_categoria, marca, ds_modelo, 
            ano_fabmod, origem_veiculo, propriedade, combustivel, obs, ativo,   
            fl_atendimento, usuario, dt_transacao, dt_inicio_db, dt_fim_db
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'sucesso': True, 'id_veiculo': novo_id})
    
    except Exception as e:
        print(f"Erro ao cadastrar: {str(e)}")
        return jsonify({
            'sucesso': False,
            'mensagem': str(e)
        }), 500
        
@app.route('/api/veiculos/atualizar', methods=['POST'])
@login_required
def atualizar_veiculo():
    try:
        cursor = mysql.connection.cursor()
        
        # Form data - CORRIGIDO: usar request.json consistentemente
        id_veiculo = request.json.get('id_veiculo')
        nu_placa = request.json.get('nu_placa', '').upper()
        id_categoria = request.json.get('id_categoria')
        marca = request.json.get('marca', '')
        ds_modelo = request.json.get('ds_modelo', '')
        ano_fabmod = request.json.get('ano_fabmod', '')
        origem_veiculo = request.json.get('origem_veiculo', '')
        propriedade = request.json.get('propriedade', '')
        combustivel = request.json.get('combustivel', '')
        obs = request.json.get('obs', '')
        ativo = request.json.get('ativo', 'S')
        fl_atendimento = request.json.get('fl_atendimento', 'N')
        usuario = session.get('usuario_id')
        dt_inicio = request.json.get('dt_inicio')  # CORRIGIDO
        dt_fim = request.json.get('dt_fim')  # CORRIGIDO

        # Get current timestamp in Manaus timezone
        manaus_tz = timezone('America/Manaus')
        dt_transacao = datetime.now(manaus_tz).strftime('%d/%m/%Y %H:%M:%S')

        # Convert DT_INICIO from DD/MM/YYYY to YYYY-MM-DD
        if dt_inicio:
            dia, mes, ano = dt_inicio.split('/')
            dt_inicio_db = f"{ano}-{mes}-{dia}"
        else:
            dt_inicio_db = None
        
        # Convert DT_FIM from DD/MM/YYYY to YYYY-MM-DD if provided
        dt_fim_db = None
        if dt_fim:
            dia, mes, ano = dt_fim.split('/')
            dt_fim_db = f"{ano}-{mes}-{dia}"

        # Update query
        query = """
        UPDATE CAD_VEICULOS SET
            NU_PLACA = %s,
            ID_CATEGORIA = %s,
            MARCA = %s,
            DS_MODELO = %s,
            ANO_FABMOD = %s,
            ORIGEM_VEICULO = %s,
            PROPRIEDADE = %s,
            COMBUSTIVEL = %s,
            OBS = %s,
            ATIVO = %s,
            FL_ATENDIMENTO = %s,
            USUARIO = %s,
            DT_TRANSACAO = %s,
            DT_INICIO = %s,
            DT_FIM = %s
        WHERE ID_VEICULO = %s
        """
        
        cursor.execute(query, (
            nu_placa, id_categoria, marca, ds_modelo, 
            ano_fabmod, origem_veiculo, propriedade, combustivel, 
            obs, ativo, fl_atendimento, usuario, dt_transacao,
            dt_inicio_db, dt_fim_db, id_veiculo
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'sucesso': True, 'mensagem': 'Veículo atualizado com sucesso'})
        
    except Exception as e:
        print(f"Erro ao atualizar: {str(e)}")
        return jsonify({
            'sucesso': False,
            'mensagem': str(e)
        }), 500
        
@app.route('/api/categorias_veiculos', methods=['GET'])
@login_required
def listar_categorias():
    try:
        cursor = mysql.connection.cursor()
        
        cursor.execute("SELECT * FROM CATEGORIA_VEICULO ORDER BY DS_CAT_VEICULO")
        
        categorias = []
        columns = [column[0] for column in cursor.description]
        
        for row in cursor.fetchall():
            categoria = {}
            for i, col in enumerate(columns):
                categoria[col.lower()] = row[i]
            categorias.append(categoria)
        
        cursor.close()
        return jsonify(categorias)
        
    except Exception as e:
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500

########################################

@app.route('/api/fluxo_lista_veiculos_pesquisa')
@login_required
def fluxo_lista_veiculos_pesquisa():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT v.ID_VEICULO, 
                   CONCAT(v.DS_MODELO, ' - ', v.NU_PLACA) AS VEICULO
            FROM CAD_VEICULOS v
            INNER JOIN FLUXO_VEICULOS f ON v.ID_VEICULO = f.ID_VEICULO
            WHERE v.ATIVO = 'S'
            ORDER BY v.DS_MODELO, v.NU_PLACA
        """)
        veiculos = cursor.fetchall()
        cursor.close()
        
        lista_veiculos = []
        for veiculo in veiculos:
            lista_veiculos.append({
                'ID_VEICULO': veiculo[0],
                'VEICULO': veiculo[1]
            })
        
        return jsonify(lista_veiculos)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/fluxo_lista_motoristas_pesquisa')
@login_required
def fluxo_lista_motoristas_pesquisa():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT m.ID_MOTORISTA, m.NM_MOTORISTA
            FROM CAD_MOTORISTA m
            INNER JOIN FLUXO_VEICULOS f ON m.ID_MOTORISTA = f.ID_MOTORISTA
            WHERE m.ATIVO = 'S' AND f.ID_MOTORISTA > 0
            ORDER BY m.NM_MOTORISTA
        """)
        motoristas = cursor.fetchall()
        cursor.close()
        
        lista_motoristas = []
        for motorista in motoristas:
            lista_motoristas.append({
                'ID_MOTORISTA': motorista[0],
                'NM_MOTORISTA': motorista[1]
            })
        
        return jsonify(lista_motoristas)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/fluxo_pesquisar')
@login_required
def fluxo_pesquisar():
    try:
        usar_periodo = request.args.get('usarPeriodo') == 'true'
        data_inicio = request.args.get('dataInicio', '').strip()
        data_fim = request.args.get('dataFim', '').strip()
        id_veiculo = request.args.get('veiculo', '').strip()
        id_motorista = request.args.get('motorista', '').strip()
        
        print(f"Parâmetros recebidos: usar_periodo={usar_periodo}, data_inicio={data_inicio}, data_fim={data_fim}, id_veiculo={id_veiculo}, id_motorista={id_motorista}")
        
        cursor = mysql.connection.cursor()
        
        # Query base
        base_query = """
            SELECT f.ID_FLUXO, f.SETOR_SOLICITANTE, f.DESTINO,
                   CONCAT(v.DS_MODELO, ' - ', v.NU_PLACA) AS VEICULO,
                   CASE 
                       WHEN f.ID_MOTORISTA = 0 OR f.ID_MOTORISTA IS NULL THEN 
                           CONCAT('*', COALESCE(f.NC_CONDUTOR, 'NÃO INFORMADO')) 
                       ELSE 
                           COALESCE(m.NM_MOTORISTA, 'MOTORISTA NÃO ENCONTRADO') 
                   END AS NOME_MOTORISTA,
                   CASE 
                       WHEN f.DATA_SAIDA IS NOT NULL AND f.HORA_SAIDA IS NOT NULL THEN
                           CONCAT(DATE_FORMAT(f.DATA_SAIDA, '%%d/%%m/%%Y'), ' ', TIME_FORMAT(f.HORA_SAIDA, '%%H:%%i'))
                       WHEN f.DT_SAIDA IS NOT NULL AND f.DT_SAIDA != '' THEN
                           CONCAT(f.DT_SAIDA, ' ', COALESCE(f.HR_SAIDA, ''))
                       ELSE 'Data não informada'
                   END AS DATAHORA_SAIDA,
                   CASE 
                       WHEN f.DATA_RETORNO IS NOT NULL AND f.HORA_RETORNO IS NOT NULL THEN
                           CONCAT(DATE_FORMAT(f.DATA_RETORNO, '%%d/%%m/%%Y'), ' ', TIME_FORMAT(f.HORA_RETORNO, '%%H:%%i'))
                       WHEN f.DT_RETORNO IS NOT NULL AND f.DT_RETORNO != '' THEN
                           CONCAT(f.DT_RETORNO, ' ', COALESCE(f.HR_RETORNO, ''))
                       ELSE NULL
                   END AS DATAHORA_RETORNO,
                   COALESCE(
                       CASE WHEN f.OBS IS NOT NULL AND f.OBS != '' THEN f.OBS END,
                       CASE WHEN f.OBS_RETORNO IS NOT NULL AND f.OBS_RETORNO != '' THEN f.OBS_RETORNO END,
                       ''
                   ) AS OBS
            FROM FLUXO_VEICULOS f
            INNER JOIN CAD_VEICULOS v ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN CAD_MOTORISTA m ON f.ID_MOTORISTA = m.ID_MOTORISTA AND f.ID_MOTORISTA > 0
        """
        
        # Construir condições WHERE
        where_conditions = []
        params = []
        
        # Filtro por período
        if usar_periodo and data_inicio and data_fim:
            where_conditions.append("""
                (
                    (f.DATA_SAIDA BETWEEN %s AND %s) OR
                    (f.DATA_RETORNO BETWEEN %s AND %s) OR
                    (f.DATA_SAIDA <= %s AND (f.DATA_RETORNO IS NULL OR f.DATA_RETORNO >= %s))
                )
            """)
            params.extend([data_inicio, data_fim, data_inicio, data_fim, data_inicio, data_fim])
        
        # Filtro por veículo
        if id_veiculo:
            where_conditions.append("f.ID_VEICULO = %s")
            params.append(int(id_veiculo))
        
        # Filtro por motorista
        if id_motorista:
            where_conditions.append("f.ID_MOTORISTA = %s")
            params.append(int(id_motorista))
        
        # Verificar se pelo menos um filtro foi aplicado
        if not where_conditions:
            return jsonify({'erro': 'Pelo menos um filtro deve ser aplicado'}), 400
        
        # Montar query final
        if where_conditions:
            query = base_query + " WHERE " + " AND ".join(where_conditions)
        else:
            query = base_query
            
        query += " ORDER BY f.DATA_SAIDA DESC, f.HORA_SAIDA DESC LIMIT 500"
        
        print(f"Query final: {query}")
        print(f"Parâmetros: {params}")
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()
        
        print(f"Encontrados {len(results)} resultados")
        
        lista_resultados = []
        for result in results:
            lista_resultados.append({
                'id_fluxo': result[0] or 0,
                'setor_solicitante': result[1] or '',
                'destino': result[2] or '',
                'veiculo': result[3] or '',
                'nome_motorista': result[4] or '',
                'datahora_saida': result[5] or '',
                'datahora_retorno': result[6],
                'obs': result[7] or ''
            })
        
        return jsonify(lista_resultados)
        
    except Exception as e:
        print(f"Erro completo na pesquisa: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'erro': f'Erro interno: {str(e)}'}), 500

#######################################

def criar_registro_locacao_fornecedor(id_demanda):
    """
    Cria registro na CONTROLE_LOCACAO_ITENS para locações com fornecedor
    Retorna o ID_ITEM criado ou None em caso de erro
    """
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        # Buscar dados da demanda
        cursor.execute("""
            SELECT ad.DT_INICIO, ad.DT_FIM, ad.SETOR, ad.DESTINO, ad.NU_SEI, 
                ad.ID_TIPOVEICULO, ad.HORARIO, 
                COALESCE(cl.ID_CL, 0) AS ID_CL
            FROM AGENDA_DEMANDAS ad
            JOIN TIPO_VEICULO tv ON tv.ID_TIPOVEICULO = ad.ID_TIPOVEICULO
            LEFT JOIN CONTROLE_LOCACAO cl ON cl.ID_FORNECEDOR = tv.ID_FORNECEDOR
            WHERE ID_AD = %s
        """, (id_demanda,))
        
        demanda = cursor.fetchone()
        
        if not demanda:
            app.logger.error(f"Demanda {id_demanda} não encontrada")
            return None
        
        # Desempacotar TODOS os 8 valores retornados pela query
        dt_inicio, dt_fim, setor, destino, nu_sei, id_tipoveiculo, horario, id_cl = demanda
        
        # Obter próximo ID_ITEM
        id_item = obter_proximo_id_item()
        
        # Obter usuário da sessão
        usuario = session.get('usuario_login', 'SISTEMA')
        
        # Extrair ano e mês da DT_FIM
        if isinstance(dt_fim, str):
            dt_fim_obj = datetime.strptime(dt_fim, '%Y-%m-%d')
        else:
            dt_fim_obj = dt_fim
        
        id_exercicio = dt_fim_obj.year
        id_mes = dt_fim_obj.month
        
        # Converter datas para formato brasileiro (string)
        if isinstance(dt_inicio, str):
            dt_inicio_obj = datetime.strptime(dt_inicio, '%Y-%m-%d')
        else:
            dt_inicio_obj = dt_inicio
        
        dt_inicial_br = dt_inicio_obj.strftime('%d/%m/%Y')
        dt_final_br = dt_fim_obj.strftime('%d/%m/%Y')
        
        # Converter horário para formato hh:mm (garantir que seja string)
        if isinstance(horario, timedelta):
            total_segundos = int(horario.total_seconds())
            horas = total_segundos // 3600
            minutos = (total_segundos % 3600) // 60
            hr_inicial = f"{horas:02d}:{minutos:02d}"
        elif isinstance(horario, str):
            hr_inicial = horario[:5]  # manter só hh:mm
        else:
            hr_inicial = None

        # Inserir registro
        cursor.execute("""
            INSERT INTO CONTROLE_LOCACAO_ITENS 
            (ID_ITEM, ID_CL, ID_EXERCICIO, SETOR_SOLICITANTE, OBJETIVO, ID_MES, ID_VEICULO_LOC, DT_INICIAL, 
            HR_INICIAL, DT_FINAL, NU_SEI, FL_EMAIL, FL_STATUS, USUARIO, DATA_INICIO, DATA_FIM, ID_AD)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'N', 'P', %s, %s, %s, %s)
        """, (
            id_item,
            id_cl,
            id_exercicio,
            setor,
            destino,
            id_mes,
            id_tipoveiculo,
            dt_inicial_br,
            hr_inicial,
            dt_final_br,
            nu_sei,
            usuario,
            dt_inicio,  # Data no formato original (YYYY-MM-DD)
            dt_fim,      # Data no formato original (YYYY-MM-DD)
            id_demanda
        ))
        
        mysql.connection.commit()
        
        app.logger.info(f"Registro de locação criado: ID_ITEM={id_item} para demanda {id_demanda}")
        
        return id_item
        
    except Exception as e:
        if cursor:
            mysql.connection.rollback()
        app.logger.error(f"Erro ao criar registro de locação: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if cursor:
            cursor.close()


# Rota principal da agenda
@app.route('/agendasegeop')
@login_required
def agendasegeop():
    return render_template('agenda_segeop.html')

# API: Listar semanas com dados
@app.route('/api/agenda/semanas', methods=['GET'])
@login_required
def listar_semanas():
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT DISTINCT 
                DATE(DT_INICIO) as data_inicio,
                DATE(DT_FIM) as data_fim
            FROM AGENDA_DEMANDAS
            WHERE DT_INICIO IS NOT NULL AND DT_FIM IS NOT NULL
            ORDER BY DT_INICIO
        """)
        
        rows = cursor.fetchall()
        
        # Se não houver dados, retornar semana atual
        if not rows:
            hoje = datetime.now().date()
            domingo = hoje - timedelta(days=hoje.weekday() + 1 if hoje.weekday() != 6 else 0)
            fim = domingo + timedelta(days=6)
            return jsonify([{
                'inicio': domingo.strftime('%Y-%m-%d'),
                'fim': fim.strftime('%Y-%m-%d'),
                'label': f"{domingo.strftime('%d/%m')} - {fim.strftime('%d/%m/%Y')}"
            }])
        
        semanas_dict = {}
        
        # Para cada demanda, processar TODAS as semanas entre início e fim
        for row in rows:
            dt_inicio = row[0]
            dt_fim = row[1]
            
            # Processar cada dia entre início e fim da demanda
            dias_diff = (dt_fim - dt_inicio).days + 1
            
            for i in range(dias_diff):
                dt_atual = dt_inicio + timedelta(days=i)
                
                # Ajustar para domingo (início da semana)
                dias_ate_domingo = (dt_atual.weekday() + 1) % 7
                inicio_semana = dt_atual - timedelta(days=dias_ate_domingo)
                fim_semana = inicio_semana + timedelta(days=6)
                
                chave = inicio_semana.strftime('%Y-%m-%d')
                if chave not in semanas_dict:
                    semanas_dict[chave] = {
                        'inicio': inicio_semana.strftime('%Y-%m-%d'),
                        'fim': fim_semana.strftime('%Y-%m-%d'),
                        'label': f"{inicio_semana.strftime('%d/%m')} - {fim_semana.strftime('%d/%m/%Y')}"
                    }
        
        semanas = sorted(semanas_dict.values(), key=lambda x: x['inicio'])
        return jsonify(semanas)
        
    except Exception as e:
        print(f"Erro em listar_semanas: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'semanas': []}), 500
    finally:
        if cursor:
            cursor.close()

# Decorator para medir tempo de queries
def log_query_time(query_name):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            elapsed = (time.time() - start) * 1000  # em milissegundos
            print(f"⏱️  [{query_name}] levou {elapsed:.2f}ms")
            return result
        return wrapper
    return decorator

@app.route('/api/agenda/dados', methods=['GET'])
@cache.cached(timeout=30, query_string=True)
@login_required
def buscar_dados_agenda():
    tempo_total_inicio = time.time()
    cursor = None
    tempos = {}  # Dicionário para armazenar os tempos
    
    try:
        inicio = request.args.get('inicio')
        fim = request.args.get('fim')
        
        print(f"\n{'='*60}")
        print(f"🔍 DIAGNÓSTICO DE PERFORMANCE - Agenda")
        print(f"📅 Período: {inicio} até {fim}")
        print(f"{'='*60}\n")

        cursor = mysql.connection.cursor()

        # ========== QUERY UNIFICADA DE MOTORISTAS (1 query ao invés de 4) ==========
        t_motoristas = time.time()
        cursor.execute("""
            SELECT DISTINCT
                m.ID_MOTORISTA, 
                m.NM_MOTORISTA, 
                m.CAD_MOTORISTA, 
                m.NU_TELEFONE, 
                m.TIPO_CADASTRO,
                m.ORDEM_LISTA,
                CASE 
                    WHEN m.TIPO_CADASTRO IN ('Motorista Atendimento','Terceirizado') THEN 'SEGEOP'
                    WHEN m.TIPO_CADASTRO = 'Administrativo' THEN 'ADMIN'
                    ELSE 'TODOS'
                END as CATEGORIA
            FROM CAD_MOTORISTA m
            INNER JOIN CAD_MOTORISTA_PERIODOS p ON p.ID_MOTORISTA = m.ID_MOTORISTA
            WHERE m.ATIVO = 'S'
            AND p.DT_INICIO <= %s
            AND (p.DT_FIM IS NULL OR p.DT_FIM >= %s)
            ORDER BY 
                CASE 
                    WHEN m.TIPO_CADASTRO IN ('Motorista Atendimento','Terceirizado') THEN 1
                    WHEN m.TIPO_CADASTRO = 'Administrativo' THEN 2
                    ELSE 3
                END,
                m.ORDEM_LISTA, 
                m.NM_MOTORISTA
        """, (fim, inicio))
        
        # Separar motoristas por categoria
        motoristas = []
        motoristas_administrativo = []
        todos_motoristas = []
        
        for r in cursor.fetchall():
            motorista_obj = {
                'id': r[0], 
                'nome': r[1], 
                'cad': r[2] if len(r) > 2 else '', 
                'telefone': r[3] if len(r) > 3 else '', 
                'tipo': r[4] if len(r) > 4 else ''
            }
            
            categoria = r[6] if len(r) > 6 else 'TODOS'
            
            if categoria == 'SEGEOP':
                motoristas.append(motorista_obj)
            elif categoria == 'ADMIN':
                motoristas_administrativo.append(motorista_obj)
            
            # Todos recebem todos os motoristas
            todos_motoristas.append(motorista_obj)
        
        tempos['motoristas_unificado'] = (time.time() - t_motoristas) * 1000
        print(f"✅ Motoristas Unificados: {tempos['motoristas_unificado']:.2f}ms")
        print(f"   → SEGEOP: {len(motoristas)} | Admin: {len(motoristas_administrativo)} | Todos: {len(todos_motoristas)}")

        # ========== 4. OUTROS MOTORISTAS ==========
        t4 = time.time()
        query_outros = """
            SELECT DISTINCT m.ID_MOTORISTA, m.NM_MOTORISTA, m.CAD_MOTORISTA, 
                m.NU_TELEFONE, m.TIPO_CADASTRO
            FROM CAD_MOTORISTA m
            INNER JOIN CAD_MOTORISTA_PERIODOS p ON p.ID_MOTORISTA = m.ID_MOTORISTA
            INNER JOIN AGENDA_DEMANDAS ae ON ae.ID_MOTORISTA = m.ID_MOTORISTA
            WHERE m.TIPO_CADASTRO NOT IN ('Motorista Atendimento','Terceirizado','Administrativo')
            AND ae.ID_TIPODEMANDA != 8
            AND m.ATIVO = 'S'
            AND p.DT_INICIO <= %s
            AND (p.DT_FIM IS NULL OR p.DT_FIM >= %s)
            AND ae.DT_INICIO <= %s 
            AND ae.DT_FIM >= %s
            UNION 
            SELECT DISTINCT 0 as ID_MOTORISTA, 
                CONCAT(NC_MOTORISTA, ' (Não Cadastrado)') as NM_MOTORISTA, 
                '' AS CAD_MOTORISTA, 
                '' AS NU_TELEFONE, 
                'Não Cadastrado' as TIPO_CADASTRO
            FROM AGENDA_DEMANDAS
            WHERE ID_TIPODEMANDA != 8
            AND DT_INICIO <= %s 
            AND DT_FIM >= %s
            AND ID_MOTORISTA = 0
            AND NC_MOTORISTA IS NOT NULL
            AND NC_MOTORISTA != ''
            ORDER BY NM_MOTORISTA
        """
        cursor.execute(query_outros, (fim, inicio, fim, inicio, fim, inicio))
        outros_motoristas = []
        for r in cursor.fetchall():
            outros_motoristas.append({
                'id': r[0], 
                'nome': r[1], 
                'cad': r[2] if len(r) > 2 else '', 
                'telefone': r[3] if len(r) > 3 else '', 
                'tipo': r[4] if len(r) > 4 else ''
            })
        tempos['outros_motoristas'] = (time.time() - t4) * 1000
        print(f"✅ Outros Motoristas: {tempos['outros_motoristas']:.2f}ms ({len(outros_motoristas)} registros)")

        # ========== 5. DEMANDAS (GERALMENTE A MAIS PESADA) ==========
        t5 = time.time()
        cursor.execute("""
            SELECT ae.ID_AD, ae.ID_MOTORISTA, 
                   CASE 
                       WHEN ae.ID_MOTORISTA = 0 THEN CONCAT(ae.NC_MOTORISTA, ' (Não Cadast.)')
                       ELSE m.NM_MOTORISTA 
                   END as NOME_MOTORISTA, 
                   ae.ID_TIPOVEICULO, td.DE_TIPODEMANDA, ae.ID_TIPODEMANDA, 
                   tv.DE_TIPOVEICULO, ae.ID_VEICULO, ae.DT_INICIO, ae.DT_FIM,
                   ae.SETOR, ae.SOLICITANTE, ae.DESTINO, ae.NU_SEI, 
                   ae.DT_LANCAMENTO, ae.USUARIO, ae.OBS, ae.SOLICITADO, ae.HORARIO,
                   ae.TODOS_VEICULOS, ae.NC_MOTORISTA, m.TIPO_CADASTRO
            FROM AGENDA_DEMANDAS ae
            LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ae.ID_MOTORISTA
            LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
            LEFT JOIN TIPO_VEICULO tv ON tv.ID_TIPOVEICULO = ae.ID_TIPOVEICULO
            WHERE ae.DT_INICIO <= %s AND ae.DT_FIM >= %s
            ORDER BY 
                CASE 
                    WHEN ae.ID_TIPOVEICULO = 7 THEN 1
                    WHEN ae.ID_TIPOVEICULO = 8 THEN 2
                    WHEN ae.ID_TIPOVEICULO = 9 THEN 3
                    ELSE 4
                END,
                ae.ID_AD ASC
        """, (fim, inicio))
        
        t5_processamento = time.time()
        demandas = []
        for r in cursor.fetchall():
            dt_lancamento = r[14].strftime('%Y-%m-%d %H:%M:%S') if r[14] else ''
            
            horario = ''
            if r[18]:
                try:
                    if isinstance(r[18], str):
                        horario = r[18][:5] if len(r[18]) >= 5 else ''
                    elif hasattr(r[18], 'total_seconds'):
                        total_seconds = int(r[18].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        if hours > 0 or minutes > 0:
                            horario = f"{hours:02d}:{minutes:02d}"
                    elif hasattr(r[18], 'strftime'):
                        horario_formatted = r[18].strftime('%H:%M')
                        if horario_formatted != '00:00':
                            horario = horario_formatted
                except Exception as e:
                    print(f"Erro ao formatar horário: {e}, tipo: {type(r[18])}, valor: {r[18]}")
                    horario = ''
            
            demandas.append({
                'id': r[0], 
                'id_motorista': r[1], 
                'nm_motorista': r[2],
                'id_tipoveiculo': r[3], 
                'de_tipodemanda': r[4], 
                'id_tipodemanda': r[5],
                'de_tipoveiculo': r[6], 
                'id_veiculo': r[7], 
                'dt_inicio': r[8].strftime('%Y-%m-%d'), 
                'dt_fim': r[9].strftime('%Y-%m-%d'),
                'setor': r[10] or '', 
                'solicitante': r[11] or '', 
                'destino': r[12] or '', 
                'nu_sei': r[13] or '', 
                'dt_lancamento': dt_lancamento,
                'usuario': r[15] or '',
                'obs': r[16] or '',
                'solicitado': r[17] or 'N',
                'horario': horario,
                'todos_veiculos': r[19] or 'N',
                'nc_motorista': r[20] or '',
				'tipo_cadastro': r[21] or ''
            })
        
        tempos['demandas_query'] = (t5_processamento - t5) * 1000
        tempos['demandas_processamento'] = (time.time() - t5_processamento) * 1000
        tempos['demandas_total'] = (time.time() - t5) * 1000
        print(f"✅ Demandas - Query: {tempos['demandas_query']:.2f}ms")
        print(f"✅ Demandas - Processamento: {tempos['demandas_processamento']:.2f}ms")
        print(f"🔥 Demandas - TOTAL: {tempos['demandas_total']:.2f}ms ({len(demandas)} registros)")

        # ========== 6. DIÁRIAS TERCEIRIZADOS ==========
        t6 = time.time()
        cursor.execute("""
            SELECT 
                dt.IDITEM,
                dt.ID_AD,
                dt.FL_EMAIL
            FROM DIARIAS_TERCEIRIZADOS dt
            INNER JOIN AGENDA_DEMANDAS ad ON ad.ID_AD = dt.ID_AD
            WHERE ad.DT_INICIO <= %s AND ad.DT_FIM >= %s
        """, (fim, inicio))
        
        diarias_terceirizados = []
        for r in cursor.fetchall():
            diarias_terceirizados.append({
                'iditem': r[0],
                'id_ad': r[1],
                'fl_email': r[2] or 'N'
            })
        tempos['diarias'] = (time.time() - t6) * 1000
        print(f"✅ Diárias Terceirizados: {tempos['diarias']:.2f}ms ({len(diarias_terceirizados)} registros)")

        # ========== QUERY UNIFICADA DE VEÍCULOS (1 query ao invés de 2) ==========
        t_veiculos = time.time()
        cursor.execute("""
            SELECT 
                v.ID_VEICULO, 
                CASE WHEN v.ORIGEM_VEICULO='Propria' THEN v.DS_MODELO
                ELSE CONCAT(v.DS_MODELO,' (',v.PROPRIEDADE,')') END AS DS_MODELO, 
                v.NU_PLACA,
                v.FL_ATENDIMENTO,
                CASE WHEN v.FL_ATENDIMENTO = 'S' THEN 1 ELSE 2 END as ORDEM_TIPO,
                cv.ORDEM_CAT,
                CASE WHEN v.ORIGEM_VEICULO = 'Propria' THEN 1 ELSE 2 END as ORDEM_ORIGEM
            FROM CAD_VEICULOS v
            LEFT JOIN CATEGORIA_VEICULO cv ON cv.ID_CAT_VEICULO = v.ID_CATEGORIA
            LEFT JOIN AGENDA_DEMANDAS ad ON ad.ID_VEICULO = v.ID_VEICULO 
                AND ad.DT_INICIO <= %s 
                AND ad.DT_FIM >= %s
            WHERE v.ATIVO = 'S'
              AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
              AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
              AND (
                  v.FL_ATENDIMENTO = 'S' 
                  OR (v.FL_ATENDIMENTO = 'N' AND ad.ID_VEICULO IS NOT NULL)
              )
            GROUP BY v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA, v.FL_ATENDIMENTO, 
                     v.ORIGEM_VEICULO, cv.ORDEM_CAT
            ORDER BY 
                ORDEM_TIPO,
                ORDEM_ORIGEM DESC,
                cv.ORDEM_CAT,
                v.DS_MODELO,
                v.NU_PLACA
        """, (fim, inicio, fim, inicio))
        
        veiculos = []
        veiculos_extras = []
        
        for r in cursor.fetchall():
            veiculo_obj = {
                'id': r[0],
                'veiculo': f"{r[1]} - {r[2]}",
                'modelo': r[1],
                'placa': r[2]
            }
            
            fl_atendimento = r[3] if len(r) > 3 else 'N'
            
            if fl_atendimento == 'S':
                veiculos.append(veiculo_obj)
            else:
                veiculos_extras.append(veiculo_obj)
        
        tempos['veiculos_unificado'] = (time.time() - t_veiculos) * 1000
        print(f"✅ Veículos Unificados: {tempos['veiculos_unificado']:.2f}ms")
        print(f"   → Padrão: {len(veiculos)} | Extras: {len(veiculos_extras)}")

        # ========== RESUMO FINAL ==========
        tempo_total = (time.time() - tempo_total_inicio) * 1000
        tempos['total'] = tempo_total
        
        print(f"\n{'='*60}")
        print(f"📊 RESUMO DE PERFORMANCE")
        print(f"{'='*60}")
        
        # Ordena por tempo (mais lento primeiro)
        sorted_tempos = sorted(
            [(k, v) for k, v in tempos.items() if k != 'total'],
            key=lambda x: x[1],
            reverse=True
        )
        
        for nome, tempo_ms in sorted_tempos:
            percentual = (tempo_ms / tempo_total) * 100
            barra = '█' * int(percentual / 2)
            print(f"{nome:25} {tempo_ms:8.2f}ms [{percentual:5.1f}%] {barra}")
        
        print(f"{'='*60}")
        print(f"⏱️  TEMPO TOTAL: {tempo_total:.2f}ms ({tempo_total/1000:.2f}s)")
        print(f"{'='*60}\n")

        return jsonify({
            'motoristas': motoristas,
            'motoristas_administrativo': motoristas_administrativo,
            'outros_motoristas': outros_motoristas,
            'todos_motoristas': todos_motoristas,
            'demandas': demandas,
            'diarias_terceirizados': diarias_terceirizados,
            'veiculos': veiculos,
            'veiculos_extras': veiculos_extras,
            '_debug': {
                'tempo_total_ms': tempo_total,
                'tempo_total_s': tempo_total / 1000,
                'detalhamento': tempos
            }
        })

    except Exception as e:
        print(f"❌ ERRO em buscar_dados_agenda: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e), 
            'motoristas': [],
            'motoristas_administrativo': [],
            'outros_motoristas': [],
            'todos_motoristas': [],
            'demandas': [], 
            'diarias_terceirizados': [],
            'veiculos': [],
            'veiculos_extras': []
        }), 500
    finally:
        if cursor:
            cursor.close()
			
# ============================================================
# BLOCO 1: ROTA DE VERIFICAÇÃO DE SINCRONIZAÇÃO
# Adicionar após a rota /api/agenda/dados
# ============================================================

@app.route('/api/agenda/check-updates', methods=['GET'])
@login_required
def check_agenda_updates():
    """Verifica se houve alterações na agenda desde o último check"""
    cursor = None
    try:
        ultimo_check = request.args.get('last_check')
        
        if not ultimo_check:
            return jsonify({'has_updates': False})
        
        usuario_atual = session.get('usuario_login', '')
        
        cursor = mysql.connection.cursor()
        
        # ===== BUSCAR em tabela de LOG em vez de SYNC =====
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                CONVERT_TZ(NOW(), '+00:00', '-04:00') as agora_local
            FROM AGENDA_ALTERACOES_LOG 
            WHERE CONVERT_TZ(DATA_ALTERACAO, '+00:00', '-04:00') > %s
              AND USUARIO_ALTERACAO != %s
        """, (ultimo_check, usuario_atual))
        
        result = cursor.fetchone()
        count = result[0]
        agora_local = result[1]
        
        # Formatar timestamp corretamente
        if agora_local:
            last_update = agora_local.strftime('%Y-%m-%d %H:%M:%S')
        else:
            last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'has_updates': count > 0,
            'last_update': last_update
        })
        
    except Exception as e:
        app.logger.error(f"❌ Erro em check_agenda_updates: {str(e)}")
        return jsonify({'has_updates': False, 'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# ============================================================
# BLOCO 2: FUNÇÃO AUXILIAR PARA REGISTRAR ALTERAÇÕES
# Adicionar no início do arquivo, após os imports
# ============================================================

def registrar_alteracao_agenda(tipo_operacao='UPDATE'):
    """Registra uma alteração na tabela de log"""
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        # ===== INSERIR novo registro em vez de UPDATE =====
        usuario = session.get('usuario_login', '')
        
        cursor.execute("""
            INSERT INTO AGENDA_ALTERACOES_LOG 
            (TIPO_OPERACAO, USUARIO_ALTERACAO, DATA_ALTERACAO)
            VALUES (%s, %s, NOW())
        """, (tipo_operacao, usuario))
        
        mysql.connection.commit()
    except Exception as e:
        print(f"Erro ao registrar alteração: {str(e)}")
    finally:
        if cursor:
            cursor.close()

def calcular_quantidade_diarias(dt_inicio, dt_fim):
    """
    Calcula a quantidade de diárias baseado nas datas de início e fim
    - Mesmo dia: 0.5
    - Cada dia adicional: +1.0
    
    Exemplos:
    - 04/01 a 04/01 = 0.5
    - 04/01 a 05/01 = 1.5
    - 04/01 a 06/01 = 2.5
    """
    try:
        # Converter strings para date se necessário
        if isinstance(dt_inicio, str):
            dt_inicio = datetime.strptime(dt_inicio, '%Y-%m-%d').date()
        if isinstance(dt_fim, str):
            dt_fim = datetime.strptime(dt_fim, '%Y-%m-%d').date()
        
        # Calcular diferença de dias
        dias_diff = (dt_fim - dt_inicio).days
        
        # Aplicar regra: 0.5 + (dias_diff * 1.0)
        qt_diarias = 0.5 + (dias_diff * 1.0)
        
        return qt_diarias
        
    except Exception as e:
        app.logger.error(f"Erro ao calcular diárias: {str(e)}")
        return 0.5  # Valor padrão em caso de erro
		
def gerenciar_diaria_motorista_atendimento(id_ad, id_tipodemanda, id_motorista, dt_inicio, dt_fim, operacao='INSERT'):
    """
    Gerencia registro de diária para Motorista Atendimento
    
    Parâmetros:
    - id_ad: ID da demanda
    - id_tipodemanda: Tipo da demanda (deve ser 2 = Viagem)
    - id_motorista: ID do motorista
    - dt_inicio: Data de início
    - dt_fim: Data de fim
    - operacao: 'INSERT', 'UPDATE' ou 'DELETE'
    
    Regra: Apenas para ID_TIPODEMANDA=2 (Viagem) e TIPO_CADASTRO='Motorista Atendimento'
    """
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        # ===== VALIDAR SE DEVE PROCESSAR =====
        
        # 1. Verificar se é tipo Viagem (ID=2)
        if int(id_tipodemanda) != 2:
            app.logger.info(f"Diária não processada - Tipo demanda {id_tipodemanda} não é Viagem")
            return None
        
        # 2. Verificar se motorista existe e é do tipo "Motorista Atendimento"
        if not id_motorista or int(id_motorista) == 0:
            app.logger.info("Diária não processada - Motorista não cadastrado")
            return None
        
        cursor.execute("""
            SELECT ID_MOTORISTA, TIPO_CADASTRO
            FROM CAD_MOTORISTA
            WHERE ID_MOTORISTA = %s
              AND TIPO_CADASTRO = 'Motorista Atendimento'
              AND ATIVO = 'S'
        """, (id_motorista,))
        
        motorista = cursor.fetchone()
        
        if not motorista:
            app.logger.info(f"Diária não processada - Motorista {id_motorista} não é 'Motorista Atendimento'")
            return None
        
        # ===== PROCESSAR OPERAÇÃO =====
        
        if operacao == 'DELETE':
            # Excluir registro de diária
            cursor.execute("""
                DELETE FROM DIARIAS_MOTORISTAS 
                WHERE ID_AD = %s
            """, (id_ad,))
            
            linhas_afetadas = cursor.rowcount
            app.logger.info(f"Diária excluída - ID_AD: {id_ad} - Linhas: {linhas_afetadas}")
            return None
        
        elif operacao == 'INSERT':
            # Calcular quantidade de diárias
            qt_diarias = calcular_quantidade_diarias(dt_inicio, dt_fim)
            
            # Inserir novo registro
            cursor.execute("""
                INSERT INTO DIARIAS_MOTORISTAS 
                (ID_AD, ID_MOTORISTA, QT_DIARIAS, DT_REGISTRO)
                VALUES (%s, %s, %s, NOW())
            """, (id_ad, id_motorista, qt_diarias))
            
            iditem = cursor.lastrowid
            app.logger.info(f"✅ Diária criada - IDITEM: {iditem} - QT: {qt_diarias}")
            return iditem
        
        elif operacao == 'UPDATE':
            # Verificar se já existe registro
            cursor.execute("""
                SELECT IDITEM FROM DIARIAS_MOTORISTAS 
                WHERE ID_AD = %s
            """, (id_ad,))
            
            registro_existente = cursor.fetchone()
            
            if registro_existente:
                # Atualizar registro existente
                qt_diarias = calcular_quantidade_diarias(dt_inicio, dt_fim)
                
                cursor.execute("""
                    UPDATE DIARIAS_MOTORISTAS 
                    SET ID_MOTORISTA = %s,
                        QT_DIARIAS = %s,
                        DT_REGISTRO = NOW()
                    WHERE ID_AD = %s
                """, (id_motorista, qt_diarias, id_ad))
                
                app.logger.info(f"✅ Diária atualizada - ID_AD: {id_ad} - QT: {qt_diarias}")
                return registro_existente[0]
            else:
                # Se não existe, criar novo
                qt_diarias = calcular_quantidade_diarias(dt_inicio, dt_fim)
                
                cursor.execute("""
                    INSERT INTO DIARIAS_MOTORISTAS 
                    (ID_AD, ID_MOTORISTA, QT_DIARIAS, DT_REGISTRO)
                    VALUES (%s, %s, %s, NOW())
                """, (id_ad, id_motorista, qt_diarias))
                
                iditem = cursor.lastrowid
                app.logger.info(f"✅ Diária criada (no update) - IDITEM: {iditem} - QT: {qt_diarias}")
                return iditem
        
        return None
        
    except Exception as e:
        app.logger.error(f"❌ Erro ao gerenciar diária motorista: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


# API: Buscar veículos disponíveis para um período específico (COM VALIDAÇÃO DE PERÍODO)
@app.route('/api/agenda/veiculos-disponiveis', methods=['GET'])
@login_required
def buscar_veiculos_disponiveis():
    cursor = None
    try:
        dt_inicio = request.args.get('inicio')
        dt_fim = request.args.get('fim')
        id_demanda_atual = request.args.get('id_demanda', '')
        tem_horario = request.args.get('tem_horario', 'false') == 'true'

        cursor = mysql.connection.cursor()

        # Se a demanda tem horário definido, não verificar conflitos de data
        # (permite múltiplas demandas no mesmo dia com horários diferentes)
        if tem_horario:
            if id_demanda_atual:
                cursor.execute("""
                    SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                    FROM CAD_VEICULOS v
                    WHERE v.FL_ATENDIMENTO = 'S' 
                      AND v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                    ORDER BY v.DS_MODELO
                """, (dt_fim, dt_inicio))
            else:
                cursor.execute("""
                    SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                    FROM CAD_VEICULOS v
                    WHERE v.FL_ATENDIMENTO = 'S' 
                      AND v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                    ORDER BY v.DS_MODELO
                """, (dt_fim, dt_inicio))
        else:
            # Lógica original: verificar se veículo já está alocado SEM horário
            if id_demanda_atual:
                cursor.execute("""
                    SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                    FROM CAD_VEICULOS v
                    WHERE v.FL_ATENDIMENTO = 'S' 
                      AND v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM AGENDA_DEMANDAS ad
                          WHERE ad.ID_VEICULO = v.ID_VEICULO
                            AND ad.ID_TIPOVEICULO = 1
                            AND ad.ID_AD != %s
                            AND ad.DT_INICIO <= %s 
                            AND ad.DT_FIM >= %s
                            AND (ad.HORARIO IS NULL OR ad.HORARIO = '00:00:00')
                      )
                    ORDER BY v.DS_MODELO
                """, (dt_fim, dt_inicio, id_demanda_atual, dt_fim, dt_inicio))
            else:
                cursor.execute("""
                    SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                    FROM CAD_VEICULOS v
                    WHERE v.FL_ATENDIMENTO = 'S' 
                      AND v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM AGENDA_DEMANDAS ad
                          WHERE ad.ID_VEICULO = v.ID_VEICULO
                            AND ad.ID_TIPOVEICULO = 1
                            AND ad.DT_INICIO <= %s 
                            AND ad.DT_FIM >= %s
                            AND (ad.HORARIO IS NULL OR ad.HORARIO = '00:00:00')
                      )
                    ORDER BY v.DS_MODELO
                """, (dt_fim, dt_inicio, dt_fim, dt_inicio))

        veiculos = []
        for r in cursor.fetchall():
            veiculos.append({
                'id': r[0],
                'veiculo': f"{r[1]} - {r[2]}",
                'modelo': r[1],
                'placa': r[2]
            })

        return jsonify(veiculos)

    except Exception as e:
        print(f"Erro em buscar_veiculos_disponiveis: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()			

# API: Buscar tipos de demanda
@app.route('/api/agenda/tipos-demanda', methods=['GET'])
@login_required
def buscar_tipos_demanda():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT ID_TIPODEMANDA, DE_TIPODEMANDA FROM TIPO_DEMANDA ORDER BY ORDEM_EXIBICAO")
        tipos = [{'id': r[0], 'descricao': r[1]} for r in cursor.fetchall()]
        cursor.close()
        return jsonify(tipos)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/agenda/tipos-demanda-completo', methods=['GET'])
@login_required
def buscar_tipos_demanda_completo():
    """
    Retorna todos os tipos de demanda com suas configurações completas
    (cores, regras de obrigatoriedade, bloqueios, etc.)
    """
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT 
                ID_TIPODEMANDA,
                DE_TIPODEMANDA,
                COR_GRADIENTE_INICIO,
                COR_GRADIENTE_FIM,
                NEGRITO,
                MOTORISTA_OBRIGATORIO,
                TIPO_VEICULO_OBRIGATORIO,
                VEICULO_OBRIGATORIO,
                SETOR_OBRIGATORIO,
                SOLICITANTE_OBRIGATORIO,
                DESTINO_OBRIGATORIO,
                DESTINO_AUTO_PREENCHER,
                EXIBIR_CHECKBOX_SOLICITADO,
                BLOQUEAR_TIPO_VEICULO,
                BLOQUEAR_VEICULO,
                BLOQUEAR_SETOR,
                BLOQUEAR_SOLICITANTE,
                BLOQUEAR_DESTINO,
                EXIBIR_DESTINO_VEICULO,
                ORDEM_EXIBICAO,
                ATIVO
            FROM TIPO_DEMANDA
            WHERE ATIVO = 'S' OR ID_TIPODEMANDA = 16
            ORDER BY ORDEM_EXIBICAO, ID_TIPODEMANDA
        """)
        
        tipos = []
        for r in cursor.fetchall():
            tipos.append({
                'id': r[0],
                'descricao': r[1],
                'cor_inicio': r[2] or '#5fa1df',
                'cor_fim': r[3] or '#8dbde8',
                'negrito': r[4] == 'S',
                'motorista_obrigatorio': r[5] == 'S',
                'tipo_veiculo_obrigatorio': r[6] == 'S',
                'veiculo_obrigatorio': r[7] == 'S',
                'setor_obrigatorio': r[8] == 'S',
                'solicitante_obrigatorio': r[9] == 'S',
                'destino_obrigatorio': r[10] == 'S',
                'destino_auto_preencher': r[11] == 'S',
                'exibir_checkbox_solicitado': r[12] == 'S',
                'bloquear_tipo_veiculo': r[13] == 'S',
                'bloquear_veiculo': r[14] == 'S',
                'bloquear_setor': r[15] == 'S',
                'bloquear_solicitante': r[16] == 'S',
                'bloquear_destino': r[17] == 'S',
                'exibir_destino_veiculo': r[18] == 'S',
                'ordem_exibicao': r[19] or 999,
                'ativo': r[20] == 'S'
            })
        
        return jsonify(tipos)
        
    except Exception as e:
        print(f"Erro em buscar_tipos_demanda_completo: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# API: Buscar tipos de veículo
@app.route('/api/agenda/tipos-veiculo', methods=['GET'])
@login_required
def buscar_tipos_veiculo():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT ID_TIPOVEICULO, DE_TIPOVEICULO FROM TIPO_VEICULO ORDER BY ID_TIPOVEICULO")
        tipos = [{'id': r[0], 'descricao': r[1]} for r in cursor.fetchall()]
        cursor.close()
        return jsonify(tipos)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/agenda/locacoes', methods=['GET'])
@login_required
def buscar_locacoes():
    cursor = None
    try:
        inicio = request.args.get('inicio')
        fim = request.args.get('fim')
        
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT ID_ITEM, ID_MOTORISTA, DS_VEICULO_MOD, DATA_INICIO, DATA_FIM, FL_STATUS, FL_EMAIL
            FROM CONTROLE_LOCACAO_ITENS
            WHERE DATA_INICIO <= %s AND DATA_FIM >= %s
            ORDER BY DATA_INICIO
        """, (fim, inicio))

        locacoes = []
        for r in cursor.fetchall():
            locacoes.append({
                'id_item': r[0],
                'id_motorista': r[1],
                'ds_veiculo_mod': r[2] or '',
                'data_inicio': r[3].strftime('%Y-%m-%d') if r[3] else '',
                'data_fim': r[4].strftime('%Y-%m-%d') if r[4] else '',
                'fl_status': r[5] or '',
                'fl_email': r[6] or 'N'
            })
        
        return jsonify(locacoes)
        
    except Exception as e:
        print(f"Erro em buscar_locacoes: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify([])
    finally:
        if cursor:
            cursor.close()

# API: Buscar tipos de demanda filtrados por contexto
@app.route('/api/agenda/tipos-demanda-filtrados', methods=['GET'])
@login_required
def buscar_tipos_demanda_filtrados():
    cursor = None
    try:
        contexto = request.args.get('contexto', '')  # 'motorista', 'veiculo', ou vazio
        
        cursor = mysql.connection.cursor()
        
        if contexto == 'motorista':
            # Excluir ID 9 quando contexto for motorista
            cursor.execute("""
                SELECT ID_TIPODEMANDA, DE_TIPODEMANDA 
                FROM TIPO_DEMANDA 
                WHERE ID_TIPODEMANDA NOT IN (9, 10)
                ORDER BY ORDEM_EXIBICAO
            """)
        elif contexto == 'veiculo':
            # Excluir IDs 6, 7, 8 quando contexto for veículo
            cursor.execute("""
                SELECT ID_TIPODEMANDA, DE_TIPODEMANDA 
                FROM TIPO_DEMANDA 
                WHERE ID_TIPODEMANDA NOT IN (6, 7, 8)
                ORDER BY ORDEM_EXIBICAO
            """)
        else:
            # Retornar todos quando não houver contexto (edição)
            cursor.execute("""
                SELECT ID_TIPODEMANDA, DE_TIPODEMANDA 
                FROM TIPO_DEMANDA 
                ORDER BY ORDEM_EXIBICAO
            """)
        
        tipos = [{'id': r[0], 'descricao': r[1]} for r in cursor.fetchall()]
        return jsonify(tipos)
        
    except Exception as e:
        print(f"Erro em buscar_tipos_demanda_filtrados: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# API: Listar feriados
@app.route('/api/agenda/feriados', methods=['GET'])
@login_required
def listar_feriados():
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT ID_FERIADO, DESCRICAO, DT_FERIADO
            FROM AGENDA_FERIADOS
            ORDER BY DT_FERIADO
        """)
        
        feriados = []
        for r in cursor.fetchall():
            feriados.append({
                'id': r[0],
                'descricao': r[1],
                'dt_feriado': r[2].strftime('%Y-%m-%d')
            })
        
        return jsonify(feriados)
        
    except Exception as e:
        print(f"Erro em listar_feriados: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# API: Criar feriado
@app.route('/api/agenda/feriado', methods=['POST'])
@login_required
def criar_feriado():
    cursor = None
    try:
        data = request.get_json()
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            INSERT INTO AGENDA_FERIADOS (DESCRICAO, DT_FERIADO)
            VALUES (%s, %s)
        """, (data['descricao'], data['dt_feriado']))
        
        mysql.connection.commit()
        id_feriado = cursor.lastrowid
        
        return jsonify({'success': True, 'id': id_feriado})
        
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao criar feriado: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# API: Excluir feriado
@app.route('/api/agenda/feriado/<int:id_feriado>', methods=['DELETE'])
@login_required
def excluir_feriado(id_feriado):
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("DELETE FROM AGENDA_FERIADOS WHERE ID_FERIADO = %s", (id_feriado,))
        mysql.connection.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao excluir feriado: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# API: Buscar feriados por período
@app.route('/api/agenda/feriados-periodo', methods=['GET'])
@login_required
def buscar_feriados_periodo():
    cursor = None
    try:
        inicio = request.args.get('inicio')
        fim = request.args.get('fim')
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT ID_FERIADO, DESCRICAO, DT_FERIADO
            FROM AGENDA_FERIADOS
            WHERE DT_FERIADO BETWEEN %s AND %s
            ORDER BY DT_FERIADO
        """, (inicio, fim))
        
        feriados = []
        for r in cursor.fetchall():
            feriados.append({
                'id': r[0],
                'descricao': r[1],
                'dt_feriado': r[2].strftime('%Y-%m-%d')
            })
        
        return jsonify(feriados)
        
    except Exception as e:
        print(f"Erro em buscar_feriados_periodo: {str(e)}")
        return jsonify([])
    finally:
        if cursor:
            cursor.close()

# API: Verificar se veículo tem demandas com horário no período
@app.route('/api/agenda/verificar-horario-veiculo', methods=['GET'])
@login_required
def verificar_horario_veiculo():
    cursor = None
    try:
        id_veiculo = request.args.get('id_veiculo')
        dt_inicio = request.args.get('inicio')
        dt_fim = request.args.get('fim')
        id_demanda_atual = request.args.get('id_demanda', '')
        
        cursor = mysql.connection.cursor()
        
        if id_demanda_atual:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM AGENDA_DEMANDAS
                WHERE ID_VEICULO = %s
                  AND ID_AD != %s
                  AND DT_INICIO <= %s
                  AND DT_FIM >= %s
                  AND HORARIO IS NOT NULL
                  AND HORARIO != '00:00:00'
            """, (id_veiculo, id_demanda_atual, dt_fim, dt_inicio))
        else:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM AGENDA_DEMANDAS
                WHERE ID_VEICULO = %s
                  AND DT_INICIO <= %s
                  AND DT_FIM >= %s
                  AND HORARIO IS NOT NULL
                  AND HORARIO != '00:00:00'
            """, (id_veiculo, dt_fim, dt_inicio))
        
        resultado = cursor.fetchone()
        tem_horario = resultado[0] > 0
        
        return jsonify({'tem_horario': tem_horario})
        
    except Exception as e:
        print(f"Erro em verificar_horario_veiculo: {str(e)}")
        return jsonify({'error': str(e), 'tem_horario': False}), 500
    finally:
        if cursor:
            cursor.close()

# API: Buscar todos os veículos ativos (para expansão)
@app.route('/api/agenda/veiculos-todos', methods=['GET'])
@login_required
def buscar_veiculos_todos():
    cursor = None
    try:
        dt_inicio = request.args.get('inicio')
        dt_fim = request.args.get('fim')
        id_demanda_atual = request.args.get('id_demanda', '')
        tem_horario = request.args.get('tem_horario', 'false') == 'true'

        cursor = mysql.connection.cursor()

        # Se a demanda tem horário definido, não verificar conflitos de data
        if tem_horario:
            cursor.execute("""
                SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                FROM CAD_VEICULOS v
                WHERE v.ATIVO = 'S'
                  AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                  AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                ORDER BY v.DS_MODELO, v.NU_PLACA
            """, (dt_fim, dt_inicio))
        else:
            # Verificar se veículo já está alocado SEM horário
            if id_demanda_atual:
                cursor.execute("""
                    SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                    FROM CAD_VEICULOS v
                    WHERE v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM AGENDA_DEMANDAS ad
                          WHERE ad.ID_VEICULO = v.ID_VEICULO
                            AND ad.ID_TIPOVEICULO = 1
                            AND ad.ID_AD != %s
                            AND ad.DT_INICIO <= %s 
                            AND ad.DT_FIM >= %s
                            AND (ad.HORARIO IS NULL OR ad.HORARIO = '00:00:00')
                      )
                    ORDER BY v.DS_MODELO, v.NU_PLACA
                """, (dt_fim, dt_inicio, id_demanda_atual, dt_fim, dt_inicio))
            else:
                cursor.execute("""
                    SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                    FROM CAD_VEICULOS v
                    WHERE v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM AGENDA_DEMANDAS ad
                          WHERE ad.ID_VEICULO = v.ID_VEICULO
                            AND ad.ID_TIPOVEICULO = 1
                            AND ad.DT_INICIO <= %s 
                            AND ad.DT_FIM >= %s
                            AND (ad.HORARIO IS NULL OR ad.HORARIO = '00:00:00')
                      )
                    ORDER BY v.DS_MODELO, v.NU_PLACA
                """, (dt_fim, dt_inicio, dt_fim, dt_inicio))

        veiculos = []
        for r in cursor.fetchall():
            veiculos.append({
                'id': r[0],
                'veiculo': f"{r[1]} - {r[2]}",
                'modelo': r[1],
                'placa': r[2]
            })

        return jsonify(veiculos)

    except Exception as e:
        print(f"Erro em buscar_veiculos_todos: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# ==================== NOVAS ROTAS PARA VALIDAÇÃO DE CONFLITOS ====================

@app.route('/api/agenda/verificar-conflito-motorista', methods=['GET'])
@login_required
def verificar_conflito_motorista():
    """Verifica se um motorista já possui demandas no período"""
    cursor = None
    try:
        id_motorista = request.args.get('id_motorista')
        dt_inicio = request.args.get('dt_inicio')
        dt_fim = request.args.get('dt_fim')
        id_ad_atual = request.args.get('id_ad', '')
        
        # Validações básicas
        if not id_motorista or not dt_inicio or not dt_fim:
            return jsonify({'error': 'Parâmetros inválidos'}), 400
        
        # Motorista não cadastrado (ID=0) nunca tem conflito
        if int(id_motorista) == 0:
            return jsonify({
                'tem_conflito': False,
                'demandas_conflitantes': []
            })
        
        cursor = mysql.connection.cursor()
        
        # Buscar demandas que conflitam com o período
        if id_ad_atual:
            # Modo edição - excluir a demanda atual
            cursor.execute("""
                SELECT ae.ID_AD, ae.DT_INICIO, ae.DT_FIM, ae.SETOR, ae.DESTINO, 
                       td.DE_TIPODEMANDA, ae.NU_SEI
                FROM AGENDA_DEMANDAS ae
                LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
                WHERE ae.ID_MOTORISTA = %s
                  AND ae.ID_AD != %s
                  AND ae.DT_INICIO <= %s
                  AND ae.DT_FIM >= %s
                ORDER BY ae.DT_INICIO
            """, (id_motorista, id_ad_atual, dt_fim, dt_inicio))
        else:
            # Modo criação
            cursor.execute("""
                SELECT ae.ID_AD, ae.DT_INICIO, ae.DT_FIM, ae.SETOR, ae.DESTINO, 
                       td.DE_TIPODEMANDA, ae.NU_SEI
                FROM AGENDA_DEMANDAS ae
                LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
                WHERE ae.ID_MOTORISTA = %s
                  AND ae.DT_INICIO <= %s
                  AND ae.DT_FIM >= %s
                ORDER BY ae.DT_INICIO
            """, (id_motorista, dt_fim, dt_inicio))
        
        demandas = []
        for r in cursor.fetchall():
            demandas.append({
                'id_ad': r[0],
                'dt_inicio': r[1].strftime('%Y-%m-%d'),
                'dt_fim': r[2].strftime('%Y-%m-%d'),
                'setor': r[3] or '',
                'destino': r[4] or '',
                'tipo_demanda': r[5] or '',
                'nu_sei': r[6] or ''
            })
        
        return jsonify({
            'tem_conflito': len(demandas) > 0,
            'demandas_conflitantes': demandas
        })
        
    except Exception as e:
        print(f"Erro em verificar_conflito_motorista: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/agenda/verificar-conflito-veiculo', methods=['GET'])
@login_required
def verificar_conflito_veiculo():
    """Verifica se um veículo já possui demandas no período (SEM horário)"""
    cursor = None
    try:
        id_veiculo = request.args.get('id_veiculo')
        dt_inicio = request.args.get('dt_inicio')
        dt_fim = request.args.get('dt_fim')
        id_ad_atual = request.args.get('id_ad', '')
        tem_horario = request.args.get('tem_horario', 'false') == 'true'
        
        # Validações básicas
        if not id_veiculo or not dt_inicio or not dt_fim:
            return jsonify({'error': 'Parâmetros inválidos'}), 400
        
        cursor = mysql.connection.cursor()
        
        # Se a demanda tem horário, NÃO verificar conflito de data
        if tem_horario:
            return jsonify({
                'tem_conflito': False,
                'demandas_conflitantes': []
            })
        
        # Buscar demandas SEM horário que conflitam
        if id_ad_atual:
            cursor.execute("""
                SELECT ae.ID_AD, ae.DT_INICIO, ae.DT_FIM, ae.SETOR, ae.DESTINO,
                       td.DE_TIPODEMANDA, ae.NU_SEI, m.NM_MOTORISTA
                FROM AGENDA_DEMANDAS ae
                LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
                LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ae.ID_MOTORISTA
                WHERE ae.ID_VEICULO = %s
                  AND ae.ID_AD != %s
                  AND ae.DT_INICIO <= %s
                  AND ae.DT_FIM >= %s
                  AND (ae.HORARIO IS NULL OR ae.HORARIO = '00:00:00')
                ORDER BY ae.DT_INICIO
            """, (id_veiculo, id_ad_atual, dt_fim, dt_inicio))
        else:
            cursor.execute("""
                SELECT ae.ID_AD, ae.DT_INICIO, ae.DT_FIM, ae.SETOR, ae.DESTINO,
                       td.DE_TIPODEMANDA, ae.NU_SEI, m.NM_MOTORISTA
                FROM AGENDA_DEMANDAS ae
                LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
                LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ae.ID_MOTORISTA
                WHERE ae.ID_VEICULO = %s
                  AND ae.DT_INICIO <= %s
                  AND ae.DT_FIM >= %s
                  AND (ae.HORARIO IS NULL OR ae.HORARIO = '00:00:00')
                ORDER BY ae.DT_INICIO
            """, (id_veiculo, dt_fim, dt_inicio))
        
        demandas = []
        for r in cursor.fetchall():
            demandas.append({
                'id_ad': r[0],
                'dt_inicio': r[1].strftime('%Y-%m-%d'),
                'dt_fim': r[2].strftime('%Y-%m-%d'),
                'setor': r[3] or '',
                'destino': r[4] or '',
                'tipo_demanda': r[5] or '',
                'nu_sei': r[6] or '',
                'motorista': r[7] or ''
            })
        
        return jsonify({
            'tem_conflito': len(demandas) > 0,
            'demandas_conflitantes': demandas
        })
        
    except Exception as e:
        print(f"Erro em verificar_conflito_veiculo: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

# =============== FIM DAS NOVAS ROTAS PARA VALIDAÇÃO DE CONFLITOS ====================

@app.route('/api/agenda/diarias-motoristas', methods=['GET'])
def get_diarias_motoristas():
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        # ========== MOTORISTAS ATENDIMENTO ==========
        query_atendimento = """
            SELECT 
                m.ID_MOTORISTA,
                m.NM_MOTORISTA,
                COALESCE(m.QT_DIARIA_ACUMULADA, 0) as DIARIA_ACUMULADA,
                COALESCE(SUM(d.QT_DIARIAS), 0) as QTD_DIARIAS,
                (COALESCE(m.QT_DIARIA_ACUMULADA, 0) + COALESCE(SUM(d.QT_DIARIAS), 0)) as TOTAL_DIARIAS
            FROM CAD_MOTORISTA m
            LEFT JOIN DIARIAS_MOTORISTAS d ON m.ID_MOTORISTA = d.ID_MOTORISTA
            WHERE m.TIPO_CADASTRO = 'Motorista Atendimento'
              AND m.ATIVO = 'S'
            GROUP BY m.ID_MOTORISTA, m.NM_MOTORISTA, m.QT_DIARIA_ACUMULADA
            ORDER BY TOTAL_DIARIAS ASC
        """
        
        print(f"[DEBUG] Executando query atendimento...")
        cursor.execute(query_atendimento)
        motoristas_atendimento = cursor.fetchall()
        print(f"[DEBUG] Motoristas atendimento: {len(motoristas_atendimento)}")
        
        # Converter para dicionários
        motoristas_atendimento_dict = []
        for row in motoristas_atendimento:
            motoristas_atendimento_dict.append({
                'ID_MOTORISTA': row[0],
                'NM_MOTORISTA': row[1],
                'DIARIA_ACUMULADA': float(row[2]) if row[2] else 0.0,
                'QTD_DIARIAS': float(row[3]) if row[3] else 0.0,
                'TOTAL_DIARIAS': float(row[4]) if row[4] else 0.0
            })
        
        # ========== TERCEIRIZADOS ==========
        query_terceirizados = """
            SELECT 
                m.ID_MOTORISTA,
                m.NM_MOTORISTA,
                COALESCE(m.QT_DIARIA_ACUMULADA, 0) as DIARIA_ACUMULADA,
                COALESCE(SUM(d.QT_DIARIAS), 0) as QTD_DIARIAS,
                (COALESCE(m.QT_DIARIA_ACUMULADA, 0) + COALESCE(SUM(d.QT_DIARIAS), 0)) as TOTAL_DIARIAS
            FROM CAD_MOTORISTA m
            LEFT JOIN DIARIAS_TERCEIRIZADOS d ON m.ID_MOTORISTA = d.ID_MOTORISTA
            WHERE m.TIPO_CADASTRO = 'Terceirizado'
              AND m.ATIVO = 'S'
              AND m.ID_FORNECEDOR IS NOT NULL
            GROUP BY m.ID_MOTORISTA, m.NM_MOTORISTA, m.QT_DIARIA_ACUMULADA
            ORDER BY TOTAL_DIARIAS ASC
        """
        
        print(f"[DEBUG] Executando query terceirizados...")
        cursor.execute(query_terceirizados)
        terceirizados = cursor.fetchall()
        print(f"[DEBUG] Terceirizados: {len(terceirizados)}")
        
        # Converter para dicionários
        terceirizados_dict = []
        for row in terceirizados:
            terceirizados_dict.append({
                'ID_MOTORISTA': row[0],
                'NM_MOTORISTA': row[1],
                'DIARIA_ACUMULADA': float(row[2]) if row[2] else 0.0,
                'QTD_DIARIAS': float(row[3]) if row[3] else 0.0,
                'TOTAL_DIARIAS': float(row[4]) if row[4] else 0.0
            })
        
        cursor.close()
        
        return jsonify({
            'motoristas_atendimento': motoristas_atendimento_dict,
            'terceirizados': terceirizados_dict
        })
        
    except Exception as e:
        print(f"❌ Erro ao buscar diárias: {e}")
        import traceback
        traceback.print_exc()
        if cursor:
            cursor.close()
        return jsonify({
            'error': f'Erro ao buscar diárias: {str(e)}'
        }), 500


@app.route('/api/agenda/diarias-motoristas/atualizar', methods=['POST'])
def atualizar_diarias_motoristas():
    cursor = None
    try:
        data = request.get_json()
        tipo = data.get('tipo')  # 'atendimento' ou 'terceirizado'
        diarias = data.get('diarias')  # Lista de {id_motorista, diaria_acumulada}
        
        print(f"[DEBUG] Recebido pedido de atualização - Tipo: {tipo}, Quantidade: {len(diarias) if diarias else 0}")
        
        if not tipo or not diarias:
            return jsonify({'error': 'Dados inválidos', 'success': False}), 400
        
        cursor = mysql.connection.cursor()
        
        # Atualizar cada motorista
        usuario = session.get('usuario_login', 'SISTEMA')
        count = 0
        
        for item in diarias:
            id_motorista = item.get('id_motorista')
            diaria_acumulada = item.get('diaria_acumulada', 0)
            
            query = """
                UPDATE CAD_MOTORISTA 
                SET QT_DIARIA_ACUMULADA = %s,
                    USUARIO = %s,
                    DT_TRANSACAO = NOW()
                WHERE ID_MOTORISTA = %s
            """
            cursor.execute(query, (diaria_acumulada, usuario, id_motorista))
            count += 1
        
        mysql.connection.commit()
        cursor.close()
        
        print(f"✅ {count} motoristas atualizados com sucesso")
        
        return jsonify({
            'success': True, 
            'message': f'{count} motoristas atualizados com sucesso',
            'count': count
        })
        
    except Exception as e:
        print(f"❌ Erro ao atualizar diárias: {e}")
        import traceback
        traceback.print_exc()
        if cursor:
            cursor.close()
        mysql.connection.rollback()
        return jsonify({
            'error': f'Erro ao atualizar: {str(e)}',
            'success': False
        }), 500


@app.route('/api/agenda/diarias-motoristas/detalhes/<int:id_motorista>/<tipo>', methods=['GET'])
def get_detalhes_diarias_motorista(id_motorista, tipo):
    cursor = None
    try:
        print(f"[DEBUG] Buscando detalhes - ID: {id_motorista}, Tipo: {tipo}")
        
        cursor = mysql.connection.cursor()
        
        # Escolher a tabela correta baseado no tipo
        if tipo == 'atendimento':
            tabela_diarias = 'DIARIAS_MOTORISTAS'
        else:  # terceirizado
            tabela_diarias = 'DIARIAS_TERCEIRIZADOS'
        
        print(f"[DEBUG] Usando tabela: {tabela_diarias}")
        
        # Buscar demandas do motorista que geraram diárias
        query = f"""
            SELECT DISTINCT
                ad.DT_INICIO,
                ad.DT_FIM,
                ad.SETOR,
                ad.DESTINO,
                ad.NU_SEI,
                ad.ID_TIPOVEICULO,
                ad.ID_VEICULO
            FROM AGENDA_DEMANDAS ad
            INNER JOIN {tabela_diarias} d ON ad.ID_AD = d.ID_AD
            WHERE d.ID_MOTORISTA = %s
            ORDER BY ad.DT_INICIO DESC, ad.DT_FIM DESC
        """
        
        cursor.execute(query, (id_motorista,))
        demandas = cursor.fetchall()
        
        print(f"[DEBUG] Encontradas {len(demandas)} demandas")
        
        # Converter para dicionários
        demandas_dict = []
        for row in demandas:
            dt_inicio = row[0]
            dt_fim = row[1]
            id_tipoveiculo = row[5]
            id_veiculo = row[6]
            
            # Buscar informação do veículo
            veiculo_info = ''
            if id_veiculo:
                if id_tipoveiculo == 1:  # Oficial
                    cursor.execute("""
                        SELECT CONCAT(DS_MODELO, ' - ', NU_PLACA) 
                        FROM CAD_VEICULOS 
                        WHERE ID_VEICULO = %s
                    """, (id_veiculo,))
                    result = cursor.fetchone()
                    if result:
                        veiculo_info = result[0]
                elif id_tipoveiculo == 2:  # Locado
                    cursor.execute("""
                        SELECT DS_VEICULO_MOD 
                        FROM CONTROLE_LOCACAO_ITENS 
                        WHERE ID_ITEM = %s
                    """, (id_veiculo,))
                    result = cursor.fetchone()
                    if result and result[0]:
                        veiculo_info = f"Locado: {result[0]}"
            
            # Calcular quantidade de diárias
            if dt_inicio and dt_fim:
                if dt_inicio == dt_fim:
                    qtd_diarias = 0.5
                else:
                    diferenca = (dt_fim - dt_inicio).days
                    qtd_diarias = diferenca + 0.5
            else:
                qtd_diarias = 0
            
            # Formatar período
            if dt_inicio == dt_fim:
                periodo = dt_inicio.strftime('%d/%m/%Y') if dt_inicio else ''
            else:
                periodo_inicio = dt_inicio.strftime('%d/%m/%Y') if dt_inicio else ''
                periodo_fim = dt_fim.strftime('%d/%m/%Y') if dt_fim else ''
                periodo = f"{periodo_inicio} - {periodo_fim}"
            
            demandas_dict.append({
                'PERIODO': periodo,
                'SETOR': row[2] or '',
                'DESTINO': row[3] or '',
                'VEICULO': veiculo_info,
                'NU_SEI': row[4] or '',
                'QTD_DIARIAS': qtd_diarias
            })
        
        cursor.close()
        
        print(f"[DEBUG] Retornando {len(demandas_dict)} demandas formatadas")
        
        return jsonify({
            'demandas': demandas_dict
        })
        
    except Exception as e:
        print(f"❌ Erro ao buscar detalhes de diárias: {e}")
        import traceback
        traceback.print_exc()
        if cursor:
            cursor.close()
        return jsonify({
            'error': f'Erro ao buscar detalhes: {str(e)}'
        }), 500

@app.route('/api/agenda_busca_setor')
@login_required
def agenda_busca_setor():
    try:
        termo = request.args.get('termo', '')
        if len(termo) < 2:
            return jsonify([])
            
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT SIGLA_SETOR 
            FROM CAD_SETORES
            WHERE SIGLA_SETOR <> '*EXTERNO'
              AND SIGLA_SETOR LIKE %s
            ORDER BY SIGLA_SETOR
            LIMIT 15
        """, (f'%{termo}%',))
        
        result = cursor.fetchall()
        cursor.close()
        
        setores = [row[0] for row in result]
        return jsonify(setores)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/periodos_diarias_terceirizados')
@login_required
def periodos_diarias_terceirizados():
    """Retorna lista de períodos (mês/ano) disponíveis para o relatório"""
    try:
        cursor = mysql.connection.cursor()
        
        query = """
        SELECT DISTINCT 
            CONCAT(
                CASE MONTH(ad.DT_INICIO)
                    WHEN 1 THEN 'Janeiro'
                    WHEN 2 THEN 'Fevereiro'
                    WHEN 3 THEN 'Março'
                    WHEN 4 THEN 'Abril'
                    WHEN 5 THEN 'Maio'
                    WHEN 6 THEN 'Junho'
                    WHEN 7 THEN 'Julho'
                    WHEN 8 THEN 'Agosto'
                    WHEN 9 THEN 'Setembro'
                    WHEN 10 THEN 'Outubro'
                    WHEN 11 THEN 'Novembro'
                    WHEN 12 THEN 'Dezembro'
                END,
                '/',
                YEAR(ad.DT_INICIO)
            ) AS MES_ANO
        FROM DIARIAS_TERCEIRIZADOS dt
        JOIN AGENDA_DEMANDAS ad ON ad.ID_AD = dt.ID_AD
        ORDER BY YEAR(ad.DT_INICIO) DESC, MONTH(ad.DT_INICIO) DESC
        """
        
        cursor.execute(query)
        periodos = [row[0] for row in cursor.fetchall()]
        cursor.close()
        
        return jsonify({'periodos': periodos})
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar períodos: {str(e)}")
        return jsonify({'erro': str(e)}), 500


@app.route('/rel_diarias_terceirizados')
@login_required
def rel_diarias_terceirizados():
    """Gera o relatório de diárias de motoristas terceirizados como PDF"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        periodos = request.args.getlist('periodos')
        
        if not periodos:
            return "Nenhum período selecionado", 400
        
        cursor = mysql.connection.cursor()
        
        # Construir condições para os períodos selecionados
        condicoes_periodos = []
        for periodo in periodos:
            partes = periodo.split('/')
            if len(partes) == 2:
                mes_nome, ano = partes
                meses = {
                    'Janeiro': 1, 'Fevereiro': 2, 'Março': 3, 'Abril': 4,
                    'Maio': 5, 'Junho': 6, 'Julho': 7, 'Agosto': 8,
                    'Setembro': 9, 'Outubro': 10, 'Novembro': 11, 'Dezembro': 12
                }
                mes_num = meses.get(mes_nome)
                if mes_num:
                    condicoes_periodos.append(f"(MONTH(ad.DT_INICIO) = {mes_num} AND YEAR(ad.DT_INICIO) = {ano})")
        
        if not condicoes_periodos:
            return "Períodos inválidos", 400
        
        where_periodos = " OR ".join(condicoes_periodos)
        
        query = f"""
        SELECT 
            COALESCE(m.NM_MOTORISTA, 'Não informado') as NM_MOTORISTA,
            COALESCE(ad.NU_SEI, '-') as NU_SEI,
            ad.DT_INICIO,
            ad.DT_FIM,
            CONCAT(
                CASE MONTH(ad.DT_INICIO)
                    WHEN 1 THEN 'Janeiro' WHEN 2 THEN 'Fevereiro' WHEN 3 THEN 'Março'
                    WHEN 4 THEN 'Abril' WHEN 5 THEN 'Maio' WHEN 6 THEN 'Junho'
                    WHEN 7 THEN 'Julho' WHEN 8 THEN 'Agosto' WHEN 9 THEN 'Setembro'
                    WHEN 10 THEN 'Outubro' WHEN 11 THEN 'Novembro' WHEN 12 THEN 'Dezembro'
                END, '/', YEAR(ad.DT_INICIO)
            ) as MES_ANO,
            COALESCE(dt.QT_DIARIAS, 0) as QT_DIARIAS,
            COALESCE(dt.VL_TOTAL, 0) as VL_TOTAL,
            CASE WHEN dt.FL_EMAIL='S' THEN 'SIM' ELSE 'NÃO' END as PAGO, 
            f.NM_FORNECEDOR
        FROM DIARIAS_TERCEIRIZADOS dt
        JOIN CAD_FORNECEDOR f ON f.ID_FORNECEDOR = dt.ID_FORNECEDOR
        JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = dt.ID_MOTORISTA
        JOIN AGENDA_DEMANDAS ad ON ad.ID_AD = dt.ID_AD
        WHERE ({where_periodos}) AND ad.DT_INICIO IS NOT NULL AND ad.DT_FIM IS NOT NULL
        ORDER BY f.NM_FORNECEDOR, YEAR(ad.DT_INICIO), MONTH(ad.DT_INICIO), m.NM_MOTORISTA, ad.DT_INICIO
        """
        
        cursor.execute(query)
        raw_items = cursor.fetchall()
        cursor.close()
        
        # Filtrar dados válidos
        items = [item for item in raw_items if item[2] is not None and item[3] is not None]
        
        # Função para formatar números no padrão brasileiro
        def formatar_numero_br(valor):
            return f"{valor:.2f}".replace('.', ',')
        
        def formatar_moeda_br(valor):
            return f"R$ {valor:.2f}".replace('.', ',')
        
        # Criar PDF
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(A4), 
                               rightMargin=1*cm, leftMargin=1*cm,
                               topMargin=1*cm, bottomMargin=1*cm)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Título
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                     fontSize=18, textColor=colors.HexColor('#1a73e8'),
                                     spaceAfter=5, alignment=TA_CENTER)
        subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Normal'],
                                       fontSize=12, textColor=colors.grey,
                                       spaceAfter=10, alignment=TA_CENTER)
        
        empresa_style = ParagraphStyle('Empresa', parent=styles['Normal'],
                                      fontSize=11, textColor=colors.black,
                                      spaceAfter=10, alignment=TA_LEFT,
                                      leftIndent=0)  # Remove qualquer indentação
        
        elements.append(Paragraph('Controle de Diárias Motoristas Terceirizados', title_style))
        
        periodo_texto = periodos[0] if len(periodos) == 1 else f'Períodos Selecionados: {len(periodos)}'
        elements.append(Paragraph(f'Período: {periodo_texto}', subtitle_style))
        elements.append(Spacer(1, 0.5*cm))
        
        # Agrupar por fornecedor e período se necessário
        agrupar = len(periodos) > 1
        
        # Agrupar por fornecedor
        fornecedores_dict = {}
        for item in items:
            fornecedor = item[8]  # NM_FORNECEDOR é o índice 8
            if fornecedor not in fornecedores_dict:
                fornecedores_dict[fornecedor] = []
            fornecedores_dict[fornecedor].append(item)
        
        total_geral_diarias = 0
        total_geral_valor = 0
        
        for fornecedor, items_fornecedor in fornecedores_dict.items():
            # Nome do fornecedor
            elements.append(Paragraph(f'Empresa: {fornecedor}', empresa_style))
            
            if agrupar:
                periodos_dict = {}
                for item in items_fornecedor:
                    periodo = item[4]
                    if periodo not in periodos_dict:
                        periodos_dict[periodo] = []
                    periodos_dict[periodo].append(item)
                
                for periodo in periodos:
                    if periodo not in periodos_dict:
                        continue
                        
                    # Título do período
                    periodo_style = ParagraphStyle('Periodo', parent=styles['Normal'],
                                                  fontSize=11, textColor=colors.white,
                                                  backColor=colors.HexColor('#1a73e8'),
                                                  leftIndent=5, spaceAfter=5)
                    elements.append(Paragraph(periodo, periodo_style))
                    
                    # Cabeçalho da tabela - LARGURAS AJUSTADAS
                    data = [['Item', 'Nome', 'Nº SEI', 'Período', 'Mês/Ano', 'Diárias', 'Valor', 'Pago']]
                    
                    subtotal_diarias = 0
                    subtotal_valor = 0
                    
                    for idx, item in enumerate(periodos_dict[periodo], 1):
                        dt_inicio = item[2].strftime('%d/%m/%Y') if item[2] else '-'
                        dt_fim = item[3].strftime('%d/%m/%Y') if item[3] else '-'
                        periodo_str = dt_inicio if dt_inicio == dt_fim else f'{dt_inicio} a {dt_fim}'
                        
                        subtotal_diarias += item[5]
                        subtotal_valor += item[6]
                        
                        data.append([
                            str(idx),
                            item[0] or '-',
                            item[1] or '-',
                            periodo_str,
                            item[4] or '-',
                            formatar_numero_br(item[5]),
                            formatar_moeda_br(item[6]),
                            item[7] or 'NÃO'
                        ])
                    
                    # Subtotal
                    data.append(['', '', '', '', 'Subtotal:', formatar_numero_br(subtotal_diarias), 
                                formatar_moeda_br(subtotal_valor), ''])
                    
                    total_geral_diarias += subtotal_diarias
                    total_geral_valor += subtotal_valor
                    
                    # Criar tabela - LARGURAS AJUSTADAS (aumentado campo Nº SEI)
                    table = Table(data, colWidths=[1.5*cm, 6.3*cm, 4.7*cm, 4.5*cm, 3*cm, 2*cm, 3*cm, 2*cm])
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 10),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                        ('BACKGROUND', (0, 1), (-1, -2), colors.white),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('FONTSIZE', (0, 1), (-1, -1), 9),
                        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
                        ('ALIGN', (2, 1), (2, -1), 'CENTER'),
                        ('ALIGN', (3, 1), (3, -1), 'CENTER'),
                        ('ALIGN', (4, 1), (4, -1), 'CENTER'),
                        ('ALIGN', (5, 1), (5, -1), 'CENTER'),
                        ('ALIGN', (6, 1), (6, -1), 'RIGHT'),
                        ('ALIGN', (7, 1), (7, -1), 'CENTER'),
                        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fff3cd')),
                        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                        ('ALIGN', (4, -1), (4, -1), 'RIGHT'),
                    ]))
                    
                    elements.append(table)
                    elements.append(Spacer(1, 0.5*cm))
                    
            else:
                # Sem agrupamento por período
                data = [['Item', 'Nome', 'Nº SEI', 'Período', 'Mês/Ano', 'Diárias', 'Valor', 'Pago']]
                
                total_fornecedor_diarias = 0
                total_fornecedor_valor = 0
                
                for idx, item in enumerate(items_fornecedor, 1):
                    dt_inicio = item[2].strftime('%d/%m/%Y') if item[2] else '-'
                    dt_fim = item[3].strftime('%d/%m/%Y') if item[3] else '-'
                    periodo_str = dt_inicio if dt_inicio == dt_fim else f'{dt_inicio} a {dt_fim}'
                    
                    total_fornecedor_diarias += item[5]
                    total_fornecedor_valor += item[6]
                    
                    data.append([
                        str(idx),
                        item[0] or '-',
                        item[1] or '-',
                        periodo_str,
                        item[4] or '-',
                        formatar_numero_br(item[5]),
                        formatar_moeda_br(item[6]),
                        item[7] or 'NÃO'
                    ])
                
                data.append(['', '', '', '', 'TOTAL:', formatar_numero_br(total_fornecedor_diarias), 
                            formatar_moeda_br(total_fornecedor_valor), ''])
                
                total_geral_diarias += total_fornecedor_diarias
                total_geral_valor += total_fornecedor_valor
                
                # LARGURAS AJUSTADAS (aumentado campo Nº SEI)
                table = Table(data, colWidths=[1.5*cm, 6.3*cm, 4.7*cm, 4.5*cm, 3*cm, 2*cm, 3*cm, 2*cm])
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('BACKGROUND', (0, 1), (-1, -2), colors.white),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ('FONTSIZE', (0, 1), (-1, -1), 9),
                    ('ALIGN', (0, 1), (0, -1), 'CENTER'),
                    ('ALIGN', (2, 1), (2, -1), 'CENTER'),
                    ('ALIGN', (3, 1), (3, -1), 'CENTER'),
                    ('ALIGN', (4, 1), (4, -1), 'CENTER'),
                    ('ALIGN', (5, 1), (5, -1), 'CENTER'),
                    ('ALIGN', (6, 1), (6, -1), 'RIGHT'),
                    ('ALIGN', (7, 1), (7, -1), 'CENTER'),
                    ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#d4edda')),
                    ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, -1), (-1, -1), 11),
                    ('ALIGN', (4, -1), (4, -1), 'RIGHT'),
                ]))
                
                elements.append(table)
                elements.append(Spacer(1, 0.5*cm))
        
        # Total geral (apenas se houver múltiplos fornecedores ou períodos)
        if len(fornecedores_dict) > 1 or agrupar:
            data_total = [['', '', '', '', 'TOTAL GERAL:', formatar_numero_br(total_geral_diarias), 
                          formatar_moeda_br(total_geral_valor), '']]
            table_total = Table(data_total, colWidths=[1.5*cm, 6.3*cm, 4.7*cm, 4.5*cm, 3*cm, 2*cm, 3*cm, 2*cm])
            table_total.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d4edda')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('ALIGN', (4, 0), (4, 0), 'RIGHT'),
                ('ALIGN', (5, 0), (5, 0), 'CENTER'),
                ('ALIGN', (6, 0), (6, 0), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            elements.append(table_total)
        
        # Rodapé
        elements.append(Spacer(1, 0.5*cm))
        data_geracao = datetime.now().strftime('%d/%m/%Y às %H:%M')
        footer_style = ParagraphStyle('Footer', parent=styles['Normal'],
                                     fontSize=9, textColor=colors.grey,
                                     alignment=TA_CENTER)
        elements.append(Paragraph(f'Relatório gerado em {data_geracao}', footer_style))
        
        # Gerar PDF
        doc.build(elements)
        pdf_buffer.seek(0)
        
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'inline; filename=relatorio_diarias_terceirizados.pdf'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Erro ao gerar relatório: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return f"Erro ao gerar relatório: {str(e)}", 500
		
### fim das rotas da agenda #############################################


@app.route('/rel_passagens_emitidas')
@login_required
def rel_passagens_emitidas():
    """Gera o relatório de passagens aéreas emitidas como PDF"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        
        # Obter parâmetros
        uo = request.args.get('uo')
        dt_inicio = request.args.get('dt_inicio')
        dt_fim = request.args.get('dt_fim')
        
        if not uo or not dt_inicio or not dt_fim:
            return "Parâmetros obrigatórios: uo, dt_inicio, dt_fim", 400
        
        cursor = mysql.connection.cursor()
        
        # Converter datas do formato dd/mm/yyyy para yyyy-mm-dd
        try:
            dt_inicio_obj = datetime.strptime(dt_inicio, '%d/%m/%Y')
            dt_fim_obj = datetime.strptime(dt_fim, '%d/%m/%Y')
            dt_inicio_sql = dt_inicio_obj.strftime('%Y-%m-%d')
            dt_fim_sql = dt_fim_obj.strftime('%Y-%m-%d')
        except ValueError:
            return "Formato de data inválido. Use dd/mm/yyyy", 400
        
        query = """
            SELECT 
                pae.ID_OF,
                pae.NU_SEI,
                pae.NOME_PASSAGEIRO,
                pae.DT_EMISSAO,
                CONCAT(ao.CIDADE, '-', ao.UF_ESTADO) as ORIGEM_FORMATADA,
                CONCAT(ad.CIDADE, '-', ad.UF_ESTADO) as DESTINO_FORMATADO,
                pae.DT_EMBARQUE,
                pae.CIA,
                pae.LOCALIZADOR,
                pae.VL_TARIFA,
                pae.VL_TAXA_EXTRA,
                pae.VL_ASSENTO,
                pae.VL_TAXA_EMBARQUE,
                pae.VL_TOTAL,
                opa.SUBACAO AS PROJETO,
                opa.UNIDADE,
                opa.NU_EMPENHO
            FROM PASSAGENS_AEREAS_EMITIDAS pae
            JOIN ORCAMENTO_PASSAGENS_AEREAS opa ON opa.ID_OPA = pae.ID_OPA
            LEFT JOIN AEROPORTOS ao ON pae.CODIGO_ORIGEM = ao.CODIGO_IATA
            LEFT JOIN AEROPORTOS ad ON pae.CODIGO_DESTINO = ad.CODIGO_IATA
            WHERE opa.UO = %s
            AND pae.ATIVO = 'S'
            AND pae.DT_EMISSAO BETWEEN %s AND %s
            ORDER BY pae.ID_OF
        """
        
        cursor.execute(query, (uo, dt_inicio_sql, dt_fim_sql))
        items = cursor.fetchall()
        cursor.close()
        
        # Função para formatar moeda brasileira
        def formatar_moeda_br(valor):
            if valor is None:
                return "R$ 0,00"
            return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        
        # Função para formatar data
        def formatar_data(data):
            if data is None:
                return '-'
            if isinstance(data, str):
                return data
            return data.strftime('%d/%m/%Y')
        
        # Criar PDF com margens mínimas
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(A4), 
                               rightMargin=0.5*cm, leftMargin=0.5*cm,
                               topMargin=0.5*cm, bottomMargin=0.5*cm)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Título
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                     fontSize=14, textColor=colors.HexColor("#0c4999"),
                                     spaceAfter=5, alignment=TA_CENTER)
        subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Normal'],
                                       fontSize=11, textColor=colors.grey,
                                       spaceAfter=10, alignment=TA_CENTER)
        
        elements.append(Paragraph('Relatório de Passagens Aéreas Emitidas', title_style))
        elements.append(Paragraph(f'Período: {dt_inicio} a {dt_fim} | UO: {uo}', subtitle_style))
        elements.append(Spacer(1, 0.5*cm))
        
        if len(items) == 0:
            no_data_style = ParagraphStyle('NoData', parent=styles['Normal'],
                                          fontSize=12, textColor=colors.grey,
                                          alignment=TA_CENTER, spaceAfter=30)
            elements.append(Paragraph('Nenhum registro encontrado para o período selecionado.', no_data_style))
        else:
            # Estilos para Paragraph nas células
            cell_left_style = ParagraphStyle('CellLeft', parent=styles['Normal'],
                                            fontSize=6.5, leading=8, alignment=TA_LEFT,
                                            wordWrap='LTR', splitLongWords=True)
            cell_center_style = ParagraphStyle('CellCenter', parent=styles['Normal'],
                                              fontSize=6.5, leading=8, alignment=TA_CENTER,
                                              wordWrap='LTR', splitLongWords=True)
            
            # Cabeçalho da tabela (17 colunas)
            data = [['OF', 'Nº SEI', 'Passageiro', 'Data\nEmissão', 'Rota\nOrigem', 'Rota\nDestino',
                     'Data\nEmbarque', 'CIA', 'Localiz.', 'Projeto', 'Gestor\nProjeto', 'Empenho', 
                     'Tarifa','Extra', 'Assento', 'Taxa\nEmb.', 'Total R$']]
            
            # Totalizadores
            total_tarifa = 0
            total_taxa_extra = 0
            total_assento = 0
            total_taxa_emb = 0
            total_geral = 0
            
            # Adicionar linhas
            for item in items:
                # CORREÇÃO: Os índices corretos dos valores na query são:
                # item[9] = VL_TARIFA
                # item[10] = VL_TAXA_EXTRA
                # item[11] = VL_ASSENTO
                # item[12] = VL_TAXA_EMBARQUE
                # item[13] = VL_TOTAL
                
                # Somar totais
                total_tarifa += item[9] if item[9] else 0
                total_taxa_extra += item[10] if item[10] else 0
                total_assento += item[11] if item[11] else 0
                total_taxa_emb += item[12] if item[12] else 0
                total_geral += item[13] if item[13] else 0
                
                # Tratar valores que podem ser None e criar Paragraphs para células que precisam quebrar
                passageiro_texto = str(item[2]) if item[2] is not None else '-'
                projeto_texto = str(item[14]) if item[14] is not None else '-'
                
                # Criar Paragraphs para permitir quebra de linha
                passageiro_para = Paragraph(passageiro_texto, cell_left_style)
                projeto_para = Paragraph(projeto_texto, cell_left_style)
                
                # Nova ordem das colunas conforme seu layout:
                # OF, Nº SEI, Passageiro, Data Emissão, Rota Origem, Rota Destino, 
                # Dt. Emb., CIA, Loc., Projeto, Gestor Projeto, Empenho,
                # Tarifa, Extra, Assento, Taxa Emb., Total R$
                
                data.append([
                    str(item[0]) if item[0] else '-',            # OF
                    str(item[1]) if item[1] else '-',            # Nº SEI  
                    passageiro_para,                             # Passageiro (com quebra)
                    formatar_data(item[3]),                      # Data Emissão
                    str(item[4]) if item[4] else '-',            # Rota Origem
                    str(item[5]) if item[5] else '-',            # Rota Destino
                    formatar_data(item[6]),                      # Dt. Emb.
                    str(item[7]) if item[7] else '-',            # CIA
                    str(item[8]) if item[8] else '-',            # Loc.
                    projeto_para,                                # Projeto (com quebra)
                    str(item[15])[:6] if item[15] else '-',      # Gestor Projeto (UNIDADE)
                    str(item[16]) if item[16] else '-',          # Empenho (NU_EMPENHO)
                    formatar_moeda_br(item[9]),                  # Tarifa (VL_TARIFA)
                    formatar_moeda_br(item[10]),                 # Extra (VL_TAXA_EXTRA)
                    formatar_moeda_br(item[11]),                 # Assento (VL_ASSENTO)
                    formatar_moeda_br(item[12]),                 # Taxa Emb. (VL_TAXA_EMBARQUE)
                    formatar_moeda_br(item[13])                  # Total R$ (VL_TOTAL)
                ])
            
            # Primeira linha de total (17 colunas)
            # Mescla da coluna 0 até 11 (OF até Empenho) = 12 colunas
            # Colunas 12-16: valores individuais (Tarifa, Extra, Assento, Taxa Emb., Total)
            data.append([
                'VALOR TOTAL:', '', '', '', '', '', '', '', '', '', '', '',  # 12 células (OF até Empenho)
                formatar_moeda_br(total_tarifa),                 # Tarifa
                formatar_moeda_br(total_taxa_extra),             # Extra
                formatar_moeda_br(total_assento),                # Assento
                formatar_moeda_br(total_taxa_emb),               # Taxa Emb.
                formatar_moeda_br(total_geral)                   # Total
            ])
            
            # Segunda linha de total (17 colunas)
            # Primeiras 12 células vazias (serão mescladas verticalmente com a linha acima)
            # Últimas 5 colunas mescladas com o valor total geral
            data.append([
                '', '', '', '', '', '', '', '', '', '', '', '',  # 12 células vazias (OF até Empenho)
                formatar_moeda_br(total_geral), '', '', '', ''   # Total geral mesclado nas últimas 5 colunas
            ])
            
            # Criar tabela com larguras em cm (17 colunas)
            col_widths = [
                0.5*cm,   # OF 
                3.0*cm,   # Nº SEI 
                2.5*cm,   # Passageiro 
                1.3*cm,   # Data Emissão
                2.2*cm,   # Rota Origem 
                2.2*cm,   # Rota Destino 
                1.3*cm,   # Dt. Emb.
                1.0*cm,   # CIA 
                1.3*cm,   # Loc.
                3.2*cm,   # Projeto 
                1.0*cm,   # Gestor Projeto
                1.8*cm,   # Empenho                
                1.7*cm,   # Tarifa
                1.3*cm,   # Extra
                1.3*cm,   # Assento
                1.3*cm,   # Taxa Emb.
                1.7*cm    # Total R$  
            ]  
            
            table = Table(data, colWidths=col_widths, repeatRows=1)
            
            # Estilo da tabela
            table_style = TableStyle([
                # Cabeçalho
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d0d0d0')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 6.8),
                ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
                
                # Corpo da tabela (até antes das duas linhas de total)
                ('FONTNAME', (0, 1), (-1, -3), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -3), 6.5),
                ('VALIGN', (0, 1), (-1, -3), 'TOP'),
                ('ALIGN', (0, 1), (0, -3), 'CENTER'),  # OF
                ('ALIGN', (1, 1), (1, -3), 'CENTER'),  # Nº SEI
                ('ALIGN', (3, 1), (3, -3), 'CENTER'),  # Data Emissão
                ('ALIGN', (4, 1), (4, -3), 'CENTER'),  # Rota Origem
                ('ALIGN', (5, 1), (5, -3), 'CENTER'),  # Rota Destino
                ('ALIGN', (6, 1), (6, -3), 'CENTER'),  # Dt. Embarque
                ('ALIGN', (7, 1), (7, -3), 'CENTER'),  # CIA
                ('ALIGN', (8, 1), (8, -3), 'CENTER'),  # Loc.
                ('ALIGN', (10, 1), (11, -3), 'CENTER'),  # Gestor Projeto e Empenho
                ('ALIGN', (12, 1), (16, -3), 'RIGHT'),  # Todos os valores (Tarifa até Total)
                
                # Padding um pouco maior para legibilidade
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                
                # Bordas normais em toda a tabela
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#666666')),
                
                # Zebrado (só no corpo, não nas linhas de total)
                ('ROWBACKGROUNDS', (0, 1), (-1, -3), [colors.HexColor('#f9f9f9'), colors.white]),
                
                # ====== PRIMEIRA LINHA DE TOTAL (penúltima linha = -2) ======
                ('SPAN', (0, -2), (11, -2)),  # Mescla células 0-11 (OF até Empenho) na primeira linha
                ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#d4edda')),  # Fundo verde em todas
                ('FONTNAME', (0, -2), (-1, -2), 'Helvetica-Bold'),
                ('FONTSIZE', (0, -2), (-1, -2), 7),
                ('ALIGN', (0, -2), (0, -2), 'RIGHT'),      # "VALOR TOTAL:" alinhado à direita
                ('ALIGN', (12, -2), (-1, -2), 'RIGHT'),    # Valores alinhados à direita
                ('VALIGN', (0, -2), (-1, -2), 'MIDDLE'),
                
                # ====== SEGUNDA LINHA DE TOTAL (última linha = -1) ======
                # Mescla vertical da célula "VALOR TOTAL:" (colunas 0-11 das linhas -2 e -1)
                ('SPAN', (0, -2), (11, -1)),  # Mescla vertical das colunas 0-11 nas duas linhas
                
                # Aplicar fundo verde claro nas colunas 0-11 da segunda linha (mesma cor da linha 1)
                ('BACKGROUND', (0, -1), (11, -1), colors.HexColor('#d4edda')),  # Verde claro
                
                # Mescla horizontal das últimas 5 colunas (12-16) na segunda linha
                ('SPAN', (12, -1), (16, -1)),  # Mescla colunas 12-16 na última linha
                
                # Aplicar fundo verde MAIS ESCURO apenas nas últimas 5 colunas (12-16)
                ('BACKGROUND', (12, -1), (16, -1), colors.HexColor('#b8dac0')),  # Verde mais escuro
                
                ('FONTNAME', (12, -1), (16, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (12, -1), (16, -1), 9),  # Fonte 2px maior (7 + 2 = 9)
                ('ALIGN', (12, -1), (16, -1), 'CENTER'),  # CENTRALIZADO
                ('VALIGN', (12, -1), (16, -1), 'MIDDLE'),
            ])
            
            table.setStyle(table_style)
            elements.append(table)
        
        # Rodapé
        rodape_style = ParagraphStyle('Rodape', parent=styles['Normal'],
                                     fontSize=8, textColor=colors.grey,
                                     alignment=TA_CENTER, spaceAfter=0)
        elements.append(Spacer(1, 0.5*cm))
        data_geracao = datetime.now().strftime('%d/%m/%Y às %H:%M:%S')
        elements.append(Paragraph(f'Relatório gerado em {data_geracao}', rodape_style))
        
        # Gerar PDF
        doc.build(elements)
        pdf_buffer.seek(0)
        
        # Retornar PDF
        return send_file(pdf_buffer, mimetype='application/pdf', 
                        as_attachment=False, 
                        download_name=f'relatorio_passagens_{uo}_{dt_inicio.replace("/", "")}_{dt_fim.replace("/", "")}.pdf')
    
    except Exception as e:
        print(f"Erro ao gerar relatório de passagens: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"Erro ao gerar relatório: {str(e)}", 500


######################### fim relatorio de passagem ##################

@app.route('/api/criar_locacao_fornecedor', methods=['POST'])
@login_required
def criar_locacao_fornecedor():
    """
    Cria registro na CONTROLE_LOCACAO_ITENS para locação com fornecedor
    COM emissão WebSocket
    """
    try:
        data = request.get_json()
        id_demanda = data.get('id_demanda')
        
        if not id_demanda:
            return jsonify({'erro': 'ID da demanda não informado'}), 400
        
        # Criar registro (função existente)
        id_item = criar_registro_locacao_fornecedor(id_demanda)
        
        if not id_item:
            return jsonify({'erro': 'Erro ao criar registro de locação'}), 500
        
        # ===== EMITIR WEBSOCKET =====
        usuario_atual = session.get('usuario_login', '')
        
        try:
            payload = {
                'tipo': 'INSERT',
                'entidade': 'LOCACAO_FORNECEDOR',
                'id_item': id_item,
                'id_demanda': id_demanda,
                'usuario': usuario_atual,
                'timestamp': datetime.now().isoformat()
            }
            
            socketio.emit('alteracao_agenda', payload, room='agenda')
            
            print(f"📡 WebSocket: INSERT LOCACAO_FORNECEDOR - ID_ITEM: {id_item}")
            
        except Exception as e:
            print(f"❌ Erro ao emitir WebSocket: {str(e)}")
        
        # Retornar sucesso (mesma estrutura de antes)
        return jsonify({
            'success': True,
            'id_item': id_item,
            'mensagem': 'Registro de locação criado com sucesso'
        })
            
    except Exception as e:
        app.logger.error(f"Erro em criar_locacao_fornecedor: {str(e)}")
        return jsonify({'erro': str(e)}), 500
    			
###...casdastro do tipo de demanda.###

@app.route('/api/tipo-demanda', methods=['GET'])
@login_required
def listar_tipo_demanda():
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT 
                ID_TIPODEMANDA,
                DE_TIPODEMANDA,
                COR_GRADIENTE_INICIO,
                COR_GRADIENTE_FIM,
                NEGRITO,
                MOTORISTA_OBRIGATORIO,
                TIPO_VEICULO_OBRIGATORIO,
                VEICULO_OBRIGATORIO,
                SETOR_OBRIGATORIO,
                SOLICITANTE_OBRIGATORIO,
                DESTINO_OBRIGATORIO,
                DESTINO_AUTO_PREENCHER,
                EXIBIR_CHECKBOX_SOLICITADO,
                BLOQUEAR_TIPO_VEICULO,
                BLOQUEAR_VEICULO,
                BLOQUEAR_SETOR,
                BLOQUEAR_SOLICITANTE,
                BLOQUEAR_DESTINO,
                ORDEM_EXIBICAO,
                ATIVO
            FROM TIPO_DEMANDA
            ORDER BY ORDEM_EXIBICAO, DE_TIPODEMANDA
        """)
        
        tipos = []
        for r in cursor.fetchall():
            tipos.append({
                'id': r[0],
                'descricao': r[1],
                'corInicio': r[2],
                'corFim': r[3],
                'negrito': r[4],
                'motoristaObrigatorio': r[5],
                'tipoVeiculoObrigatorio': r[6],
                'veiculoObrigatorio': r[7],
                'setorObrigatorio': r[8],
                'solicitanteObrigatorio': r[9],
                'destinoObrigatorio': r[10],
                'destinoAutoPreencher': r[11],
                'exibirCheckboxSolicitado': r[12],
                'bloquearTipoVeiculo': r[13],
                'bloquearVeiculo': r[14],
                'bloquearSetor': r[15],
                'bloquearSolicitante': r[16],
                'bloquearDestino': r[17],
                'ordemExibicao': r[18],
                'ativo': r[19]
            })
        
        return jsonify(tipos)
        
    except Exception as e:
        print(f"Erro em listar_tipo_demanda: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/tipo-demanda/<int:id>', methods=['GET'])
@login_required
def obter_tipo_demanda(id):
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT 
                ID_TIPODEMANDA, DE_TIPODEMANDA, COR_GRADIENTE_INICIO,
                COR_GRADIENTE_FIM, NEGRITO, MOTORISTA_OBRIGATORIO,
                TIPO_VEICULO_OBRIGATORIO, VEICULO_OBRIGATORIO,
                SETOR_OBRIGATORIO, SOLICITANTE_OBRIGATORIO,
                DESTINO_OBRIGATORIO, DESTINO_AUTO_PREENCHER,
                EXIBIR_CHECKBOX_SOLICITADO, BLOQUEAR_TIPO_VEICULO,
                BLOQUEAR_VEICULO, BLOQUEAR_SETOR,
                BLOQUEAR_SOLICITANTE, BLOQUEAR_DESTINO,
                ORDEM_EXIBICAO, ATIVO
            FROM TIPO_DEMANDA
            WHERE ID_TIPODEMANDA = %s
        """, (id,))
        
        r = cursor.fetchone()
        if not r:
            return jsonify({'error': 'Tipo de demanda não encontrado'}), 404
        
        tipo = {
            'id': r[0], 'descricao': r[1], 'corInicio': r[2],
            'corFim': r[3], 'negrito': r[4], 'motoristaObrigatorio': r[5],
            'tipoVeiculoObrigatorio': r[6], 'veiculoObrigatorio': r[7],
            'setorObrigatorio': r[8], 'solicitanteObrigatorio': r[9],
            'destinoObrigatorio': r[10], 'destinoAutoPreencher': r[11],
            'exibirCheckboxSolicitado': r[12], 'bloquearTipoVeiculo': r[13],
            'bloquearVeiculo': r[14], 'bloquearSetor': r[15],
            'bloquearSolicitante': r[16], 'bloquearDestino': r[17],
            'ordemExibicao': r[18], 'ativo': r[19]
        }
        
        return jsonify(tipo)
        
    except Exception as e:
        print(f"Erro em obter_tipo_demanda: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/tipo-demanda', methods=['POST'])
@login_required
def criar_tipo_demanda():
    cursor = None
    try:
        data = request.get_json()
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            INSERT INTO TIPO_DEMANDA (
                DE_TIPODEMANDA, COR_GRADIENTE_INICIO, COR_GRADIENTE_FIM,
                NEGRITO, MOTORISTA_OBRIGATORIO, TIPO_VEICULO_OBRIGATORIO,
                VEICULO_OBRIGATORIO, SETOR_OBRIGATORIO, SOLICITANTE_OBRIGATORIO,
                DESTINO_OBRIGATORIO, DESTINO_AUTO_PREENCHER, EXIBIR_CHECKBOX_SOLICITADO,
                BLOQUEAR_TIPO_VEICULO, BLOQUEAR_VEICULO, BLOQUEAR_SETOR,
                BLOQUEAR_SOLICITANTE, BLOQUEAR_DESTINO, ORDEM_EXIBICAO, ATIVO
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            data.get('descricao'),
            data.get('corInicio', '#5fa1df'),
            data.get('corFim', '#8dbde8'),
            data.get('negrito', 'N'),
            data.get('motoristaObrigatorio', 'S'),
            data.get('tipoVeiculoObrigatorio', 'S'),
            data.get('veiculoObrigatorio', 'N'),
            data.get('setorObrigatorio', 'N'),
            data.get('solicitanteObrigatorio', 'N'),
            data.get('destinoObrigatorio', 'N'),
            data.get('destinoAutoPreencher', 'N'),
            data.get('exibirCheckboxSolicitado', 'N'),
            data.get('bloquearTipoVeiculo', 'N'),
            data.get('bloquearVeiculo', 'N'),
            data.get('bloquearSetor', 'N'),
            data.get('bloquearSolicitante', 'N'),
            data.get('bloquearDestino', 'N'),
            data.get('ordemExibicao', 999),
            data.get('ativo', 'S')
        ))
        
        mysql.connection.commit()
        
        return jsonify({
            'message': 'Tipo de demanda criado com sucesso',
            'id': cursor.lastrowid
        }), 201
        
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro em criar_tipo_demanda: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/tipo-demanda/<int:id>', methods=['PUT'])
@login_required
def atualizar_tipo_demanda(id):
    cursor = None
    try:
        data = request.get_json()
        
        cursor = mysql.connection.cursor()
        cursor.execute("""
            UPDATE TIPO_DEMANDA SET
                DE_TIPODEMANDA = %s,
                COR_GRADIENTE_INICIO = %s,
                COR_GRADIENTE_FIM = %s,
                NEGRITO = %s,
                MOTORISTA_OBRIGATORIO = %s,
                TIPO_VEICULO_OBRIGATORIO = %s,
                VEICULO_OBRIGATORIO = %s,
                SETOR_OBRIGATORIO = %s,
                SOLICITANTE_OBRIGATORIO = %s,
                DESTINO_OBRIGATORIO = %s,
                DESTINO_AUTO_PREENCHER = %s,
                EXIBIR_CHECKBOX_SOLICITADO = %s,
                BLOQUEAR_TIPO_VEICULO = %s,
                BLOQUEAR_VEICULO = %s,
                BLOQUEAR_SETOR = %s,
                BLOQUEAR_SOLICITANTE = %s,
                BLOQUEAR_DESTINO = %s,
                ORDEM_EXIBICAO = %s,
                ATIVO = %s
            WHERE ID_TIPODEMANDA = %s
        """, (
            data.get('descricao'),
            data.get('corInicio'),
            data.get('corFim'),
            data.get('negrito'),
            data.get('motoristaObrigatorio'),
            data.get('tipoVeiculoObrigatorio'),
            data.get('veiculoObrigatorio'),
            data.get('setorObrigatorio'),
            data.get('solicitanteObrigatorio'),
            data.get('destinoObrigatorio'),
            data.get('destinoAutoPreencher'),
            data.get('exibirCheckboxSolicitado'),
            data.get('bloquearTipoVeiculo'),
            data.get('bloquearVeiculo'),
            data.get('bloquearSetor'),
            data.get('bloquearSolicitante'),
            data.get('bloquearDestino'),
            data.get('ordemExibicao'),
            data.get('ativo'),
            id
        ))
        
        mysql.connection.commit()
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Tipo de demanda não encontrado'}), 404
        
        return jsonify({'message': 'Tipo de demanda atualizado com sucesso'})
        
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro em atualizar_tipo_demanda: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/tipo-demanda/<int:id>', methods=['DELETE'])
@login_required
def deletar_tipo_demanda(id):
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("DELETE FROM TIPO_DEMANDA WHERE ID_TIPODEMANDA = %s", (id,))
        mysql.connection.commit()
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Tipo de demanda não encontrado'}), 404
        
        return jsonify({'message': 'Tipo de demanda deletado com sucesso'})
        
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro em deletar_tipo_demanda: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


# Rota para renderizar a página HTML
@app.route('/tipo-demanda')
@login_required
def pagina_tipo_demanda():
    return render_template('tipo_demanda.html')


@app.route('/api/verificar_email_fornecedor_enviado')
def verificar_email_fornecedor_enviado():
    id_ad = request.args.get('id_ad', type=int)
    
    if not id_ad:
        return jsonify({'erro': 'ID_AD não informado'}), 400
    
    try:
        cursor = mysql.connection.cursor()
        
        # Verificar se existe registro na tabela EMAIL_OUTRAS_LOCACOES
        cursor.execute("""
            SELECT ID_EMAIL, DATA_HORA
            FROM EMAIL_OUTRAS_LOCACOES
            WHERE ID_AD = %s
            ORDER BY ID_EMAIL DESC
            LIMIT 1
        """, (id_ad,))
        resultado = cursor.fetchone()
        cursor.close()
        
        if resultado:
            id_email, data_hora = resultado
            return jsonify({
                'email_enviado': True,
                'id_email': id_email,
                'data_hora': data_hora
            })
        else:
            return jsonify({
                'email_enviado': False
            })
        
    except Exception as e:
        app.logger.error(f'Erro ao verificar e-mail de fornecedor: {e}')
        return jsonify({'erro': str(e)}), 500


######  PASSAGENS AEREAS - CÓDIGO ATUALIZADO #######

@app.route('/controle_passagens_aereas')
@login_required
def controle_passagens_aereas():
    return render_template('orcamento_passagens_aereas.html')

@app.route('/api/orcamento/dados_iniciais', methods=['GET'])
@login_required
def obter_dados_iniciais_orcamento():
    try:
        cursor = mysql.connection.cursor()
        
        # Buscar programas
        cursor.execute("SELECT ID_PROGRAMA, DE_PROGRAMA FROM PROGRAMA_ORCAMENTO ORDER BY DE_PROGRAMA")
        programas = [{'id': row[0], 'descricao': row[1]} for row in cursor.fetchall()]
        
        # Buscar ações orçamentárias
        cursor.execute("SELECT ID_AO, DE_AO FROM ACAO_ORCAMENTARIA ORDER BY DE_AO")
        acoes = [{'id': row[0], 'descricao': row[1]} for row in cursor.fetchall()]
        
        # Buscar subitens
        cursor.execute("SELECT ID_SUBITEM, DE_SUBITEM FROM SUBITEM_ORCAMENTO ORDER BY ID_SUBITEM")
        subitens = [{'id': row[0], 'descricao': row[1]} for row in cursor.fetchall()]
        
        # Buscar exercícios cadastrados
        cursor.execute("""
            SELECT DISTINCT EXERCICIO 
            FROM ORCAMENTO_PASSAGENS_AEREAS 
            ORDER BY EXERCICIO DESC
        """)
        exercicios = [row[0] for row in cursor.fetchall()]
        
        # Obter próximo ID_OPA
        cursor.execute("SELECT COALESCE(MAX(ID_OPA), 0) + 1 FROM ORCAMENTO_PASSAGENS_AEREAS")
        proximo_id = cursor.fetchone()[0]
        
        cursor.close()
        
        return jsonify({
            'success': True,
            'programas': programas,
            'acoes': acoes,
            'subitens': subitens,
            'exercicios': exercicios,
            'proximo_id': proximo_id
        })
    except Exception as e:
        print(f"Erro ao obter dados iniciais: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/orcamento/passagens/<int:id_opa>', methods=['GET'])
@login_required
def obter_orcamento_passagem(id_opa):
    try:
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT 
                ID_OPA, EXERCICIO, UO, UNIDADE, FONTE, ID_PROGRAMA, ID_AO,
                SUBACAO, OBJETIVO, ELEMENTO_DESPESA, ID_SUBITEM,
                VL_APROVADO, NU_EMPENHO
            FROM ORCAMENTO_PASSAGENS_AEREAS
            WHERE ID_OPA = %s AND ATIVO = 'S'
        """, (id_opa,))
        
        row = cursor.fetchone()
        cursor.close()
        
        if row:
            return jsonify({
                'success': True,
                'registro': {
                    'id_opa': row[0],
                    'exercicio': row[1],
                    'uo': row[2],
                    'unidade': row[3],
                    'fonte': row[4],
                    'id_programa': row[5],
                    'id_ao': row[6],
                    'subacao': row[7],
                    'objetivo': row[8],
                    'elemento_despesa': row[9],
                    'id_subitem': row[10],
                    'vl_aprovado': float(row[11]) if row[11] else 0,
                    'nu_empenho': row[12]
                }
            })
        else:
            return jsonify({'error': 'Registro não encontrado'}), 404
            
    except Exception as e:
        print(f"Erro ao obter registro: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/contratos-passagens', methods=['GET'])
@login_required
def listar_contratos_passagens():
    """
    Lista todos os contratos de passagens aéreas disponíveis
    com informações do fornecedor
    """
    cursor = None
    try:
        # ✅ MODIFICADO: Usar DictCursor para retornar dicionários
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        cursor.execute("""
            SELECT 
                c.ID_CONTROLE,
                c.ID_FORNECEDOR,
                c.EXERCICIO,
                c.PROCESSO,
                c.ATA_PREGAO,
                c.CONTRATO,
                c.SETOR_GESTOR,
                c.NOME_GESTOR,
                c.CIDADE,
                f.NM_FORNECEDOR,
                f.CNPJ_FORNECEDOR
            FROM CONTROLE_PASSAGENS_AEREAS c
            LEFT JOIN CAD_FORNECEDOR f ON c.ID_FORNECEDOR = f.ID_FORNECEDOR
            ORDER BY c.EXERCICIO DESC, c.ID_CONTROLE DESC
        """)
        
        contratos = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'contratos': contratos
        })
        
    except Exception as e:
        print(f"❌ Erro ao listar contratos: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
    finally:
        if cursor:
            cursor.close()

@app.route('/api/orcamentos-passagens/contrato/<int:id_controle>', methods=['GET'])
@login_required
def listar_orcamentos_por_contrato(id_controle):
    """
    Lista todos os orçamentos de um contrato específico
    """
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT 
                ID_OPA,
                ID_CONTROLE,
                EXERCICIO,
                UO,
                UNIDADE,
                FONTE,
                ID_PROGRAMA,
                ID_AO,
                SUBACAO,
                OBJETIVO,
                ELEMENTO_DESPESA,
                ID_SUBITEM,
                VL_APROVADO,
                NU_EMPENHO,
                USUARIO,
                DT_LANCAMENTO,
                ATIVO
            FROM ORCAMENTO_PASSAGENS_AEREAS
            WHERE ID_CONTROLE = %s
            AND ATIVO = 'S'
            ORDER BY ID_OPA DESC
        """, (id_controle,))
        
        orcamentos = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'orcamentos': orcamentos
        })
        
    except Exception as e:
        print(f"❌ Erro ao listar orçamentos por contrato: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
    finally:
        if cursor:
            cursor.close()


@app.route('/api/orcamento/passagens', methods=['POST'])
@login_required
def criar_orcamento_passagem():
    """
    Cria um novo registro de orçamento de passagens aéreas
    E automaticamente cria o registro inicial na ORCAMENTO_PASSAGENS_ITEM
    """
    cursor = None
    try:
        data = request.get_json()
        cursor = mysql.connection.cursor()
        usuario = session.get('usuario_login')
        
        # Validar e limpar dados
        fonte = ''.join(filter(str.isdigit, data.get('fonte', '')))
        unidade = data.get('unidade', '').upper()
        id_opa = data['id_opa']
        vl_aprovado = data.get('vl_aprovado')
        nu_empenho = data.get('nu_empenho')
        id_controle = data.get('id_controle')
        
        # Validar ID_CONTROLE obrigatório
        if not id_controle:
            return jsonify({
                'success': False,
                'error': 'ID_CONTROLE é obrigatório'
            }), 400
        
        # ✅ NOVO: Buscar EXERCICIO da tabela CONTROLE_PASSAGENS_AEREAS
        cursor.execute("""
            SELECT EXERCICIO 
            FROM CONTROLE_PASSAGENS_AEREAS 
            WHERE ID_CONTROLE = %s
        """, (id_controle,))
        
        resultado = cursor.fetchone()
        if not resultado:
            return jsonify({
                'success': False,
                'error': 'Contrato não encontrado'
            }), 404
        
        exercicio = resultado[0]  # ✅ EXERCICIO vem do contrato
        
        # ========================================
        # INSERT na ORCAMENTO_PASSAGENS_AEREAS
        # ========================================
        cursor.execute("""
            INSERT INTO ORCAMENTO_PASSAGENS_AEREAS 
            (ID_OPA, ID_CONTROLE, EXERCICIO, UO, UNIDADE, FONTE, ID_PROGRAMA, ID_AO, 
             SUBACAO, OBJETIVO, ELEMENTO_DESPESA, ID_SUBITEM, 
             VL_APROVADO, NU_EMPENHO, USUARIO, DT_LANCAMENTO, ATIVO)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), 'S')
        """, (
            id_opa,
            id_controle,
            exercicio,  # ✅ Usando o EXERCICIO do contrato
            data.get('uo'),
            unidade,
            fonte,
            data.get('id_programa'),
            data.get('id_ao'),
            data.get('subacao'),
            data.get('objetivo'),
            data.get('elemento_despesa', '33.90.33'),
            data.get('id_subitem'),
            vl_aprovado,
            nu_empenho,
            usuario
        ))
        
        print(f"✅ INSERT realizado na ORCAMENTO_PASSAGENS_AEREAS - ID_OPA: {id_opa}, EXERCICIO: {exercicio}")
        
        # =========================================
        # OBTER PRÓXIMO IDITEM_OPA
        # =========================================
        cursor.execute("""
            SELECT COALESCE(MAX(IDITEM_OPA), 0) + 1 
            FROM ORCAMENTO_PASSAGENS_ITEM
        """)
        proximo_iditem = cursor.fetchone()[0]
        
        print(f"📊 Próximo IDITEM_OPA: {proximo_iditem}")
        
        # =========================================
        # INSERT na ORCAMENTO_PASSAGENS_ITEM
        # =========================================
        cursor.execute("""
            INSERT INTO ORCAMENTO_PASSAGENS_ITEM
            (IDITEM_OPA, ID_OPA, IDTIPO_ITEM, FLTIPO, VL_ITEM, NU_EMPENHO, 
             OBS, USUARIO, DT_LANCAMENTO, ATIVO)
            VALUES (%s, %s, 1, 'E', 0.00, NULL, 'Registro inicial', %s, NOW(), 'S')
        """, (
            proximo_iditem,
            id_opa,
            usuario
        ))
        
        print(f"✅ INSERT realizado na ORCAMENTO_PASSAGENS_ITEM - IDITEM_OPA: {proximo_iditem}")
        
        # Commit das transações
        mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'message': 'Orçamento criado com sucesso',
            'id_opa': id_opa
        })
        
    except Exception as e:
        if mysql.connection:
            mysql.connection.rollback()
        print(f"❌ Erro ao criar orçamento: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
    finally:
        if cursor:
            cursor.close()
			

@app.route('/api/orcamento/passagens/<int:id_opa>', methods=['PUT'])
@login_required
def atualizar_orcamento_passagem(id_opa):
    """
    Atualiza um registro de orçamento de passagens aéreas
    E atualiza o lançamento inicial correspondente se VL_APROVADO ou NU_EMPENHO forem alterados
    """
    cursor = None
    try:
        data = request.get_json()
        cursor = mysql.connection.cursor()
        usuario = session.get('usuario_login')
        
        # Validar e limpar dados
        fonte = ''.join(filter(str.isdigit, data.get('fonte', '')))
        unidade = data.get('unidade', '').upper()
        vl_aprovado_novo = data.get('vl_aprovado')
        nu_empenho_novo = data.get('nu_empenho')
        
        # =========================================
        # 1. BUSCAR VALORES ATUAIS ANTES DO UPDATE
        # =========================================
        cursor.execute("""
            SELECT VL_APROVADO, NU_EMPENHO 
            FROM ORCAMENTO_PASSAGENS_AEREAS 
            WHERE ID_OPA = %s AND ATIVO = 'S'
        """, (id_opa,))
        
        resultado = cursor.fetchone()
        
        if not resultado:
            return jsonify({
                'success': False,
                'error': 'Registro não encontrado'
            }), 404
        
        vl_aprovado_antigo = float(resultado[0]) if resultado[0] else 0
        nu_empenho_antigo = resultado[1]
        
        # Verificar se os valores mudaram
        vl_aprovado_mudou = (vl_aprovado_novo != vl_aprovado_antigo)
        nu_empenho_mudou = (nu_empenho_novo != nu_empenho_antigo)
        
        print(f"📝 Atualizando ID_OPA: {id_opa}")
        print(f"   VL_APROVADO: {vl_aprovado_antigo} → {vl_aprovado_novo} (mudou: {vl_aprovado_mudou})")
        print(f"   NU_EMPENHO: '{nu_empenho_antigo}' → '{nu_empenho_novo}' (mudou: {nu_empenho_mudou})")
        
        # =========================================
        # 2. UPDATE na ORCAMENTO_PASSAGENS_AEREAS
        # =========================================
        cursor.execute("""
            UPDATE ORCAMENTO_PASSAGENS_AEREAS 
            SET EXERCICIO = %s, UO = %s, UNIDADE = %s, FONTE = %s,
                ID_PROGRAMA = %s, ID_AO = %s, SUBACAO = %s, OBJETIVO = %s,
                ELEMENTO_DESPESA = %s, ID_SUBITEM = %s,
                VL_APROVADO = %s, NU_EMPENHO = %s, USUARIO = %s, DT_LANCAMENTO = NOW()
            WHERE ID_OPA = %s AND ATIVO = 'S'
        """, (
            data['exercicio'],
            data['uo'],
            unidade,
            fonte,
            data.get('id_programa'),
            data.get('id_ao'),
            data.get('subacao'),
            data.get('objetivo'),
            data.get('elemento_despesa', '33.90.33'),
            data.get('id_subitem'),
            vl_aprovado_novo,
            nu_empenho_novo,
            usuario,
            id_opa
        ))
        
        linhas_afetadas = cursor.rowcount
        
        if linhas_afetadas == 0:
            return jsonify({
                'success': False,
                'error': 'Nenhum registro foi atualizado'
            }), 404
        
        print(f"✅ UPDATE realizado na ORCAMENTO_PASSAGENS_AEREAS - ID_OPA: {id_opa}")
        
        # =========================================
        # 3. UPDATE na ORCAMENTO_PASSAGENS_ITEM 
        #    (apenas se VL_APROVADO ou NU_EMPENHO mudaram)
        # =========================================
        if vl_aprovado_mudou or nu_empenho_mudou:
            
            # Verificar se existe lançamento inicial
            cursor.execute("""
                SELECT IDITEM_OPA, VL_ITEM, NU_EMPENHO
                FROM ORCAMENTO_PASSAGENS_ITEM
                WHERE ID_OPA = %s AND IDTIPO_ITEM = 1
                LIMIT 1
            """, (id_opa,))
            
            lancamento_inicial = cursor.fetchone()
            
            if lancamento_inicial:
                iditem_opa = lancamento_inicial[0]
                vl_item_antigo = float(lancamento_inicial[1]) if lancamento_inicial[1] else 0
                nu_empenho_item_antigo = lancamento_inicial[2]
                
                print(f"📊 Lançamento Inicial encontrado - IDITEM_OPA: {iditem_opa}")
                print(f"   Valores antigos: VL_ITEM={vl_item_antigo}, NU_EMPENHO='{nu_empenho_item_antigo}'")
                
                # Atualizar o lançamento inicial
                cursor.execute("""
                    UPDATE ORCAMENTO_PASSAGENS_ITEM
                    SET VL_ITEM = %s, 
                        NU_EMPENHO = %s,
                        USUARIO = %s,
                        DT_LANCAMENTO = NOW()
                    WHERE IDITEM_OPA = %s
                """, (
                    vl_aprovado_novo,
                    nu_empenho_novo,
                    usuario,
                    iditem_opa
                ))
                
                linhas_afetadas_item = cursor.rowcount
                
                if linhas_afetadas_item > 0:
                    print(f"✅ UPDATE realizado na ORCAMENTO_PASSAGENS_ITEM - IDITEM_OPA: {iditem_opa}")
                    print(f"   Novos valores: VL_ITEM={vl_aprovado_novo}, NU_EMPENHO='{nu_empenho_novo}'")
                else:
                    print(f"⚠️ Nenhuma linha foi atualizada na ORCAMENTO_PASSAGENS_ITEM")
                    
            else:
                # Lançamento inicial não existe - criar um novo
                print(f"⚠️ Lançamento Inicial não encontrado para ID_OPA: {id_opa}")
                print(f"🔨 Criando lançamento inicial automaticamente...")
                
                # Obter próximo IDITEM_OPA
                cursor.execute("""
                    SELECT COALESCE(MAX(IDITEM_OPA), 0) + 1 
                    FROM ORCAMENTO_PASSAGENS_ITEM
                """)
                proximo_iditem = cursor.fetchone()[0]
                
                # Criar lançamento inicial
                cursor.execute("""
                    INSERT INTO ORCAMENTO_PASSAGENS_ITEM
                    (IDITEM_OPA, ID_OPA, IDTIPO_ITEM, FLTIPO, VL_ITEM, 
                     NU_EMPENHO, OBS, USUARIO, DT_LANCAMENTO)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    proximo_iditem,
                    id_opa,
                    1,                        # IDTIPO_ITEM = 1 (lançamento inicial)
                    'E',                      # FLTIPO = Entrada
                    vl_aprovado_novo,
                    nu_empenho_novo,
                    'Lançamento Inicial',
                    usuario
                ))
                
                print(f"✅ Lançamento Inicial criado - IDITEM_OPA: {proximo_iditem}")
        else:
            print(f"ℹ️ VL_APROVADO e NU_EMPENHO não mudaram - não há necessidade de atualizar ORCAMENTO_PASSAGENS_ITEM")
        
        # =========================================
        # 4. COMMIT DAS TRANSAÇÕES
        # =========================================
        mysql.connection.commit()
        
        mensagem = 'Orçamento atualizado com sucesso!'
        if vl_aprovado_mudou or nu_empenho_mudou:
            mensagem += ' (Lançamento inicial também atualizado)'
        
        print(f"🎉 {mensagem}")
        
        return jsonify({
            'success': True, 
            'message': mensagem,
            'id_opa': id_opa,
            'vl_aprovado_mudou': vl_aprovado_mudou,
            'nu_empenho_mudou': nu_empenho_mudou
        })
        
    except Exception as e:
        # Rollback em caso de erro
        if cursor:
            mysql.connection.rollback()
        
        print(f"❌ Erro ao atualizar orçamento: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Erro ao atualizar orçamento'
        }), 500
        
    finally:
        if cursor:
            cursor.close()


@app.route('/api/orcamento/passagens/listar', methods=['GET'])
@login_required
def listar_orcamento_passagens():
    """
    Lista orçamentos com cálculo de Valor Atual
    Valor Atual = Soma(Entradas 'E') - Soma(Saídas 'S')
    MODIFICADO: Agora aceita filtro por id_controle
    """
    try:
        # ✅ MODIFICADO: Agora aceita tanto exercicio quanto id_controle
        exercicio = request.args.get('exercicio')
        id_controle = request.args.get('id_controle')  # NOVO!
        
        if not exercicio:
            from datetime import datetime
            exercicio = datetime.now().year
        
        cursor = mysql.connection.cursor()
        
        # ✅ MODIFICADO: Query agora inclui filtro opcional por ID_CONTROLE
        query = """
            SELECT 
                opa.ID_OPA,
                opa.EXERCICIO,
                opa.UO,
                opa.UNIDADE,
                opa.FONTE,
                opa.ID_PROGRAMA,
                p.DE_PROGRAMA as programa,
                opa.ID_AO,
                ao.DE_AO as acao,
                opa.SUBACAO,
                opa.OBJETIVO,
                opa.ELEMENTO_DESPESA,
                opa.ID_SUBITEM,
                CONCAT(si.ID_SUBITEM, ' - ', si.DE_SUBITEM) as subitem,
                opa.VL_APROVADO,
                opa.NU_EMPENHO,
                COALESCE(SUM(CASE WHEN pae.ATIVO = 'S' THEN pae.VL_TOTAL ELSE 0 END), 0) as vl_utilizado,
                -- Calcular Valor Atual: Soma(E) - Soma(S)
                COALESCE(
                    (SELECT 
                        SUM(CASE WHEN FLTIPO = 'E' THEN VL_ITEM ELSE -VL_ITEM END)
                     FROM ORCAMENTO_PASSAGENS_ITEM 
                     WHERE ID_OPA = opa.ID_OPA
                    ), 0
                ) as vl_atual
            FROM ORCAMENTO_PASSAGENS_AEREAS opa
            LEFT JOIN PROGRAMA_ORCAMENTO p ON opa.ID_PROGRAMA = p.ID_PROGRAMA
            LEFT JOIN ACAO_ORCAMENTARIA ao ON opa.ID_AO = ao.ID_AO
            LEFT JOIN SUBITEM_ORCAMENTO si ON opa.ID_SUBITEM = si.ID_SUBITEM
            LEFT JOIN PASSAGENS_AEREAS_EMITIDAS pae ON opa.ID_OPA = pae.ID_OPA AND pae.ATIVO = 'S'
            WHERE opa.EXERCICIO = %s
        """
        
        # ✅ NOVO: Adicionar filtro por ID_CONTROLE se fornecido
        params = [exercicio]
        if id_controle:
            query += " AND opa.ID_CONTROLE = %s"
            params.append(id_controle)
        
        query += """
            GROUP BY 
                opa.ID_OPA, opa.EXERCICIO, opa.UO, opa.UNIDADE, opa.FONTE,
                opa.ID_PROGRAMA, p.DE_PROGRAMA, opa.ID_AO, ao.DE_AO,
                opa.SUBACAO, opa.OBJETIVO, opa.ELEMENTO_DESPESA,
                opa.ID_SUBITEM, si.ID_SUBITEM, si.DE_SUBITEM,
                opa.VL_APROVADO, opa.NU_EMPENHO
            ORDER BY opa.ID_OPA
        """
        
        # ✅ MODIFICADO: Usar tuple de params em vez de apenas exercicio
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        
        registros = []
        for row in rows:
            vl_aprovado = float(row[14]) if row[14] else 0.0
            vl_utilizado = float(row[16]) if row[16] else 0.0
            vl_atual = float(row[17]) if row[17] else 0.0
            vl_saldo = vl_atual - vl_utilizado
            
            registro = {
                'id_opa': row[0],
                'exercicio': row[1],
                'uo': row[2] or '',
                'unidade': row[3] or '',
                'fonte': row[4] or '',
                'id_programa': row[5],
                'programa': row[6] or '',
                'id_ao': row[7],
                'acao': row[8] or '',
                'subacao': row[9] or '',
                'objetivo': row[10] or '',
                'elemento_despesa': row[11] or '',
                'id_subitem': row[12],
                'subitem': row[13] or '',
                'vl_aprovado': vl_aprovado,
                'vl_utilizado': vl_utilizado,
                'vl_atual': vl_atual,
                'vl_saldo': vl_saldo,
                'nu_empenho': row[15] or ''
            }
            registros.append(registro)
        
        cursor.close()
        return jsonify({'success': True, 'registros': registros})
        
    except Exception as e:
        print(f"ERRO ao listar orçamentos: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# NOVA ROTA: Buscar itens de um orçamento específico (para a subtabela)
# ============================================================================

@app.route('/api/orcamento/passagens/<int:id_opa>/itens', methods=['GET'])
@login_required
def listar_itens_orcamento(id_opa):
    """
    Lista os itens de um orçamento (para subtabela)
    Ignora IDTIPO_ITEM = 1 (lançamento inicial)
    """
    try:
        cursor = mysql.connection.cursor()
        
        query = """
            SELECT 
                opi.IDITEM_OPA,
                opi.IDTIPO_ITEM,
                t.DESCRICAO as tipo_descricao,
                opi.FLTIPO,
                opi.VL_ITEM,
                opi.NU_EMPENHO,
                opi.OBS,
                opi.USUARIO,
                opi.DT_LANCAMENTO
            FROM ORCAMENTO_PASSAGENS_ITEM opi
            INNER JOIN TIPO_ITEMOPA t ON opi.IDTIPO_ITEM = t.IDTIPO_ITEM
            WHERE opi.ID_OPA = %s 
              AND opi.IDTIPO_ITEM > 1
            ORDER BY opi.IDITEM_OPA
        """
        
        cursor.execute(query, (id_opa,))
        rows = cursor.fetchall()
        
        itens = []
        for idx, row in enumerate(rows, start=1):
            item = {
                'item': idx,
                'iditem_opa': row[0],
                'idtipo_item': row[1],
                'descricao': row[2] or '',
                'fltipo': row[3],
                'vl_item': float(row[4]) if row[4] else 0.0,
                'nu_empenho': row[5] or '',
                'obs': row[6] or '',
                'usuario': row[7] or '',
                'dt_lancamento': row[8].strftime('%d/%m/%Y %H:%M') if row[8] else ''
            }
            itens.append(item)
        
        cursor.close()
        return jsonify({'success': True, 'itens': itens})
        
    except Exception as e:
        print(f"ERRO ao listar itens: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/tipos-item-opa', methods=['GET'])
def get_tipos_item_opa():
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT IDTIPO_ITEM, DESCRICAO, FLTIPO 
            FROM TIPO_ITEMOPA 
            ORDER BY DESCRICAO
        """)
        tipos = cursor.fetchall()
        cursor.close()
        
        return jsonify({
            'success': True,
            'tipos': tipos
        })
        
    except Exception as e:
        print(f"Erro ao buscar tipos: {str(e)}")  # DEBUG
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/orcamento-passagens-itens/<int:id_opa>', methods=['GET'])
def get_itens_orcamento(id_opa):
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT 
                opi.IDITEM_OPA,
                opi.ID_OPA,
                opi.IDTIPO_ITEM,
                opi.FLTIPO,
                opi.VL_ITEM,
                opi.NU_EMPENHO,
                opi.OBS,
                opi.USUARIO,
                opi.DT_LANCAMENTO,
                ti.DESCRICAO as DESCRICAO_TIPO
            FROM ORCAMENTO_PASSAGENS_ITEM opi
            LEFT JOIN TIPO_ITEMOPA ti ON opi.IDTIPO_ITEM = ti.IDTIPO_ITEM
            WHERE ti.IDTIPO_ITEM > 1 AND opi.ID_OPA = %s
            ORDER BY opi.DT_LANCAMENTO DESC
        """, (id_opa,))
        
        itens = cursor.fetchall()
        cursor.close()
        
        print(f"Itens encontrados: {len(itens)}")  # DEBUG
        print(f"Dados: {itens}")  # DEBUG
        
        return jsonify({
            'success': True,
            'itens': itens
        })
        
    except Exception as e:
        print(f"Erro ao buscar itens: {str(e)}")  # DEBUG
        return jsonify({'success': False, 'error': str(e)}), 500
    

@app.route('/api/orcamento-passagens-itens/adicionar', methods=['POST'])
def adicionar_item_orcamento():
    try:
        dados = request.json
        print(f"Dados recebidos: {dados}")  # DEBUG
        
        cursor = mysql.connection.cursor()
        
        # Buscar próximo ID
        cursor.execute("SELECT IFNULL(MAX(IDITEM_OPA), 0) + 1 as proximo_id FROM ORCAMENTO_PASSAGENS_ITEM")
        result = cursor.fetchone()
        proximo_id = result[0] if result else 1
        
        # Obter usuário da sessão (ajuste conforme seu sistema)
        usuario = session.get('usuario', 'ADMIN')
        
        # Inserir item
        cursor.execute("""
            INSERT INTO ORCAMENTO_PASSAGENS_ITEM 
            (IDITEM_OPA, ID_OPA, IDTIPO_ITEM, FLTIPO, VL_ITEM, NU_EMPENHO, OBS, USUARIO, DT_LANCAMENTO)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            proximo_id,
            dados['id_opa'],
            dados['idtipo_item'],
            dados['fltipo'],
            dados['vl_item'],
            dados.get('nu_empenho'),
            dados.get('obs'),
            usuario
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        print(f"Item inserido com ID: {proximo_id}")  # DEBUG
        
        return jsonify({
            'success': True,
            'iditem': proximo_id
        })
        
    except Exception as e:
        print(f"Erro ao adicionar item: {str(e)}")  # DEBUG
        mysql.connection.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/orcamento-passagens-itens/excluir/<int:iditem>', methods=['DELETE'])
def excluir_item_orcamento(iditem):
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("DELETE FROM ORCAMENTO_PASSAGENS_ITEM WHERE IDITEM_OPA = %s", (iditem,))
        mysql.connection.commit()
        cursor.close()
        
        print(f"Item {iditem} excluído")  # DEBUG
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Erro ao excluir item: {str(e)}")  # DEBUG
        mysql.connection.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# MÓDULO: CONTROLE DE BILHETES - PASSAGENS AÉREAS
# ============================================================================

# ----- ROTA: PÁGINA PRINCIPAL DE CONTROLE DE BILHETES -----
@app.route('/passagens/controle')
@login_required
def passagens_controle():
    try:
        # Receber ID_CONTROLE da URL
        id_controle = request.args.get('id_controle', type=int)
        
        if not id_controle:
            flash('ID do contrato não informado', 'warning')
            return redirect(url_for('controle_passagens_aereas'))
        
        cursor = mysql.connection.cursor()
        
        # Buscar informações do contrato para exibir no cabeçalho
        cursor.execute("""
            SELECT 
                c.ID_CONTROLE, 
                c.EXERCICIO, 
                f.NM_FORNECEDOR, 
                c.PROCESSO
            FROM CONTROLE_PASSAGENS_AEREAS c
            JOIN CAD_FORNECEDOR f ON f.ID_FORNECEDOR = c.ID_FORNECEDOR
            WHERE c.ID_CONTROLE = %s
        """, (id_controle,))
        
        contrato_info = cursor.fetchone()
        
        if not contrato_info:
            cursor.close()
            flash('Contrato não encontrado', 'danger')
            return redirect(url_for('controle_passagens_aereas'))
        
        # Buscar passagens do contrato específico
        cursor.execute("""
            SELECT 
                pae.ID_OF,
                pae.ID_OPA,
                pae.ID_CONTROLE,
                pae.NU_SEI,
                pae.NOME_PASSAGEIRO,
                DATE_FORMAT(pae.DT_EMISSAO, '%%d/%%m/%%Y') as DT_EMISSAO_F,
                pae.TRECHO,
                pae.CODIGO_ORIGEM,
                pae.CODIGO_DESTINO,
                CONCAT(ao.CODIGO_IATA, ' - ', ao.CIDADE, '/', ao.UF_ESTADO) as ORIGEM_FORMATADA,
                CONCAT(ad.CODIGO_IATA, ' - ', ad.CIDADE, '/', ad.UF_ESTADO) as DESTINO_FORMATADO,
                DATE_FORMAT(pae.DT_EMBARQUE, '%%d/%%m/%%Y') as DT_EMBARQUE_F,
                pae.CIA,
                pae.LOCALIZADOR,
                FORMAT(pae.VL_TARIFA, 2, 'de_DE') as VL_TARIFA_F,
                FORMAT(pae.VL_TAXA_EXTRA, 2, 'de_DE') as VL_TAXA_EXTRA_F,
                FORMAT(pae.VL_ASSENTO, 2, 'de_DE') as VL_ASSENTO_F,
                FORMAT(pae.VL_TAXA_EMBARQUE, 2, 'de_DE') as VL_TAXA_EMBARQUE_F,
                FORMAT(pae.VL_TOTAL, 2, 'de_DE') as VL_TOTAL_F,
                pae.VL_TARIFA,
                pae.VL_TAXA_EXTRA,
                pae.VL_ASSENTO,
                pae.VL_TAXA_EMBARQUE,
                pae.VL_TOTAL,
                pae.DT_EMISSAO,
                pae.DT_EMBARQUE,
                pae.DISTANCIA_KM,
                FORMAT(pae.DISTANCIA_KM, 2, 'de_DE') as DISTANCIA_KM_F,
                opa.NU_EMPENHO
            FROM PASSAGENS_AEREAS_EMITIDAS pae
            LEFT JOIN AEROPORTOS ao ON pae.CODIGO_ORIGEM = ao.CODIGO_IATA
            LEFT JOIN AEROPORTOS ad ON pae.CODIGO_DESTINO = ad.CODIGO_IATA
            LEFT JOIN ORCAMENTO_PASSAGENS_AEREAS opa ON pae.ID_OPA = opa.ID_OPA
            WHERE pae.ATIVO = 'S'
            AND pae.ID_CONTROLE = %s
            ORDER BY pae.ID_OF
        """, (id_controle,))
        passagens = cursor.fetchall()
        
        cursor.execute("""
            SELECT DISTINCT CIA 
            FROM PASSAGENS_AEREAS_EMITIDAS 
            WHERE ATIVO = 'S' 
            AND CIA IS NOT NULL
            AND ID_CONTROLE = %s
            ORDER BY CIA
        """, (id_controle,))
        cias = cursor.fetchall()
        
        cursor.close()
        
        nome_usuario = session.get('usuario_login')
        
        # Preparar dados do contrato para o template
        contrato = {
            'id_controle': contrato_info[0],
            'exercicio': contrato_info[1],
            'empresa': contrato_info[2],
            'processo': contrato_info[3]
        }
        
        return render_template('passagens_controle.html', 
                             passagens=passagens,
                             cias=cias,
                             contrato=contrato,
                             usuario=nome_usuario)
    
    except Exception as e:
        print(f"Erro ao carregar passagens: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Erro ao carregar passagens: {str(e)}', 'danger')
        return redirect(url_for('controle_passagens_aereas'))


def obter_proximo_id_of():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT MAX(ID_OF) FROM PASSAGENS_AEREAS_EMITIDAS")
    resultado = cursor.fetchone()
    cursor.close()
    
    ultimo_id = resultado[0] if resultado[0] else 0
    return ultimo_id + 1


# ----- NOVA ROTA: BUSCAR AEROPORTOS (AUTOCOMPLETE) -----
@app.route('/api/aeroportos/buscar', methods=['GET'])
@login_required
def buscar_aeroportos():
    """
    Busca aeroportos por código IATA, cidade ou nome
    Usado para autocomplete nos campos origem/destino
    """
    try:
        termo = request.args.get('termo', '').strip()
        
        if len(termo) < 2:
            return jsonify({'success': True, 'aeroportos': []})
        
        cursor = mysql.connection.cursor()
        
        # Buscar por código IATA ou cidade
        query = """
            SELECT 
                ID_AEROPORTO,
                CODIGO_IATA,
                NOME_AEROPORTO,
                CIDADE,
                UF_ESTADO,
                PAIS,
                CODIGO_PAIS
            FROM AEROPORTOS
            WHERE ATIVO = 'S'
            AND (
                CODIGO_IATA LIKE %s
                OR CIDADE LIKE %s
                OR NOME_AEROPORTO LIKE %s
            )
            ORDER BY 
                CASE 
                    WHEN CODIGO_IATA LIKE %s THEN 1
                    WHEN CIDADE LIKE %s THEN 2
                    ELSE 3
                END,
                CIDADE
            LIMIT 15
        """
        
        termo_busca = f"%{termo}%"
        termo_inicio = f"{termo}%"
        
        cursor.execute(query, (
            termo_inicio, termo_busca, termo_busca,
            termo_inicio, termo_inicio
        ))
        
        rows = cursor.fetchall()
        cursor.close()
        
        aeroportos = []
        for row in rows:
            # Formatar display
            uf = f"/{row[4]}" if row[4] else ""
            display = f"{row[1]} - {row[3]}{uf}"
            
            aeroportos.append({
                'id': row[0],
                'codigo_iata': row[1],
                'nome': row[2],
                'cidade': row[3],
                'uf': row[4] or '',
                'pais': row[5],
                'codigo_pais': row[6],
                'display': display
            })
        
        return jsonify({
            'success': True,
            'aeroportos': aeroportos
        })
        
    except Exception as e:
        print(f"Erro ao buscar aeroportos: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ----- ROTA: OBTER DETALHES DE UMA PASSAGEM (PARA EDIÇÃO) -----
@app.route('/api/passagens/obter/<int:id_of>', methods=['GET'])
@login_required
def obter_passagem(id_of):
    """
    Obter dados de uma passagem específica para edição
    ATUALIZADA COM DISTANCIA_KM
    """
    try:
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT 
                pae.ID_OF,
                pae.ID_OPA,
                pae.ID_CONTROLE,
                pae.NU_SEI,
                pae.NOME_PASSAGEIRO,
                DATE_FORMAT(pae.DT_EMISSAO, '%%Y-%%m-%%d') as DT_EMISSAO,
                pae.TRECHO,
                pae.CODIGO_ORIGEM,
                pae.CODIGO_DESTINO,
                pae.ORIGEM,
                pae.DESTINO,
                DATE_FORMAT(pae.DT_EMBARQUE, '%%Y-%%m-%%d') as DT_EMBARQUE,
                pae.CIA,
                pae.LOCALIZADOR,
                pae.VL_TARIFA,
                pae.VL_TAXA_EXTRA,
                pae.VL_ASSENTO,
                pae.VL_TAXA_EMBARQUE,
                pae.VL_TOTAL,
                ao.CIDADE as ORIGEM_CIDADE,
                ao.UF_ESTADO as ORIGEM_UF,
                ad.CIDADE as DESTINO_CIDADE,
                ad.UF_ESTADO as DESTINO_UF,
                pae.DISTANCIA_KM
            FROM PASSAGENS_AEREAS_EMITIDAS pae
            LEFT JOIN AEROPORTOS ao ON pae.CODIGO_ORIGEM = ao.CODIGO_IATA
            LEFT JOIN AEROPORTOS ad ON pae.CODIGO_DESTINO = ad.CODIGO_IATA
            WHERE pae.ID_OF = %s AND pae.ATIVO = 'S'
        """, (id_of,))
        
        row = cursor.fetchone()
        cursor.close()
        
        if not row:
            return jsonify({
                'success': False,
                'message': 'Passagem não encontrada'
            }), 404
        
        passagem = {
            'id_of': row[0],
            'id_opa': row[1],
            'id_controle': row[2],
            'nu_sei': row[3] or '',
            'nome_passageiro': row[4] or '',
            'dt_emissao': row[5] or '',
            'trecho': row[6] or '',
            'codigo_origem': row[7] or '',
            'codigo_destino': row[8] or '',
            'origem': row[9] or '',
            'destino': row[10] or '',
            'dt_embarque': row[11] or '',
            'cia': row[12] or '',
            'localizador': row[13] or '',
            'vl_tarifa': float(row[14]) if row[14] else 0,
            'vl_taxa_extra': float(row[15]) if row[15] else 0,
            'vl_assento': float(row[16]) if row[16] else 0,
            'vl_taxa_embarque': float(row[17]) if row[17] else 0,
            'vl_total': float(row[18]) if row[18] else 0,
            'distancia_km': float(row[23]) if row[23] else 0
        }
        
        if row[7]:
            uf_origem = f"/{row[20]}" if row[20] else ""
            passagem['origem_display'] = f"{row[7]} - {row[19]}{uf_origem}"
        
        if row[8]:
            uf_destino = f"/{row[22]}" if row[22] else ""
            passagem['destino_display'] = f"{row[8]} - {row[21]}{uf_destino}"
        
        return jsonify({
            'success': True,
            'passagem': passagem
        })
        
    except Exception as e:
        print(f"Erro ao obter passagem: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erro ao buscar dados: {str(e)}'
        }), 500


# ----- ROTA: SALVAR NOVA PASSAGEM - ATUALIZADA COM CAMPOS MAIÚSCULOS -----
@app.route('/passagens/salvar', methods=['POST'])
@login_required
def passagens_salvar():
    """
    Salvar nova passagem - ATUALIZADA para gravar CIA, LOCALIZADOR e TRECHO em MAIÚSCULO
    """
    try:
        cursor = mysql.connection.cursor()
        
        # Receber dados do formulário
        id_opa = request.form.get('id_opa')
        id_controle = request.form.get('id_controle', type=int)
        nu_sei = request.form.get('nu_sei')
        nome_passageiro = request.form.get('nome_passageiro')
        dt_emissao = request.form.get('dt_emissao')
        
        # FORÇAR MAIÚSCULAS nos campos CIA, LOCALIZADOR e TRECHO
        trecho = request.form.get('trecho', '').upper()
        cia = request.form.get('cia', '').upper()
        localizador = request.form.get('localizador', '').upper()
        
        # Códigos IATA dos aeroportos
        codigo_origem = request.form.get('codigo_origem')
        codigo_destino = request.form.get('codigo_destino')
        
        # Campos de texto origem/destino (mantidos para compatibilidade)
        origem = request.form.get('origem', '')
        destino = request.form.get('destino', '')
        
        dt_embarque = request.form.get('dt_embarque')
        
        # Valores financeiros - converter de formato brasileiro
        vl_tarifa = request.form.get('vl_tarifa', '0').replace('.', '').replace(',', '.')
        vl_taxa_extra = request.form.get('vl_taxa_extra', '0').replace('.', '').replace(',', '.')
        vl_assento = request.form.get('vl_assento', '0').replace('.', '').replace(',', '.')
        vl_taxa_embarque = request.form.get('vl_taxa_embarque', '0').replace('.', '').replace(',', '.')
        vl_total = request.form.get('vl_total', '0').replace('.', '').replace(',', '.')
        distancia_km = request.form.get('distancia_km', '0').replace('.', '').replace(',', '.')
        
        # As datas já vêm no formato yyyy-mm-dd do input type="date"
        dt_emissao_sql = dt_emissao if dt_emissao else None
        dt_embarque_sql = dt_embarque if dt_embarque else None
        
        id_of = obter_proximo_id_of()
        usuario = session.get('usuario_login')
        
        # Inserir no banco
        cursor.execute("""
            INSERT INTO PASSAGENS_AEREAS_EMITIDAS (
                ID_OF, ID_OPA, ID_CONTROLE, NU_SEI, NOME_PASSAGEIRO, DT_EMISSAO,
                TRECHO, CODIGO_ORIGEM, CODIGO_DESTINO, ORIGEM, DESTINO, 
                DT_EMBARQUE, CIA, LOCALIZADOR,
                VL_TARIFA, VL_TAXA_EXTRA, VL_ASSENTO, VL_TAXA_EMBARQUE, VL_TOTAL,
                DISTANCIA_KM, ATIVO, USUARIO, DT_LANCAMENTO
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, 'S', %s, NOW()
            )
        """, (
            id_of, id_opa, id_controle, nu_sei, nome_passageiro, dt_emissao_sql,
            trecho, codigo_origem, codigo_destino, origem, destino,
            dt_embarque_sql, cia, localizador,
            vl_tarifa, vl_taxa_extra, vl_assento, vl_taxa_embarque, vl_total,
            distancia_km, usuario
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True, 'message': 'Passagem cadastrada com sucesso!'})
    
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao salvar passagem: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro ao salvar: {str(e)}'}), 500


# ----- ROTA ATUALIZADA: ATUALIZAR PASSAGEM - COM CAMPOS MAIÚSCULOS -----
@app.route('/passagens/atualizar', methods=['POST'])
@login_required
def passagens_atualizar():
    """
    Atualizar passagem - ATUALIZADA para gravar CIA, LOCALIZADOR e TRECHO em MAIÚSCULO
    """
    try:
        cursor = mysql.connection.cursor()
        
        # Receber dados do formulário
        id_of = request.form.get('id_of_edit')
        id_opa = request.form.get('id_opa_edit')
        id_controle = request.form.get('id_controle', type=int)
        nu_sei = request.form.get('nu_sei_edit')
        nome_passageiro = request.form.get('nome_passageiro_edit')
        dt_emissao = request.form.get('dt_emissao_edit')
        
        # FORÇAR MAIÚSCULAS nos campos CIA, LOCALIZADOR e TRECHO
        trecho = request.form.get('trecho_edit', '').upper()
        cia = request.form.get('cia_edit', '').upper()
        localizador = request.form.get('localizador_edit', '').upper()
        
        # Códigos IATA dos aeroportos
        codigo_origem = request.form.get('codigo_origem_edit')
        codigo_destino = request.form.get('codigo_destino_edit')
        
        # Campos de texto origem/destino
        origem = request.form.get('origem_edit', '')
        destino = request.form.get('destino_edit', '')
        
        dt_embarque = request.form.get('dt_embarque_edit')
        
        # Valores financeiros
        vl_tarifa = request.form.get('vl_tarifa_edit', '0').replace('.', '').replace(',', '.')
        vl_taxa_extra = request.form.get('vl_taxa_extra_edit', '0').replace('.', '').replace(',', '.')
        vl_assento = request.form.get('vl_assento_edit', '0').replace('.', '').replace(',', '.')
        vl_taxa_embarque = request.form.get('vl_taxa_embarque_edit', '0').replace('.', '').replace(',', '.')
        vl_total = request.form.get('vl_total_edit', '0').replace('.', '').replace(',', '.')
        distancia_km = request.form.get('distancia_km_edit', '0').replace('.', '').replace(',', '.')

        # print(f"✅ Distancia: {distancia_km}")

        # As datas já vêm no formato yyyy-mm-dd do input type="date"
        dt_emissao_sql = dt_emissao if dt_emissao else None
        dt_embarque_sql = dt_embarque if dt_embarque else None
        
        usuario = session.get('usuario_login')
        
        # Atualizar no banco
        cursor.execute("""
            UPDATE PASSAGENS_AEREAS_EMITIDAS SET
                ID_OPA = %s,
                ID_CONTROLE = %s,
                NU_SEI = %s,
                NOME_PASSAGEIRO = %s,
                DT_EMISSAO = %s,
                TRECHO = %s,
                CODIGO_ORIGEM = %s,
                CODIGO_DESTINO = %s,
                ORIGEM = %s,
                DESTINO = %s,
                DT_EMBARQUE = %s,
                CIA = %s,
                LOCALIZADOR = %s,
                VL_TARIFA = %s,
                VL_TAXA_EXTRA = %s,
                VL_ASSENTO = %s,
                VL_TAXA_EMBARQUE = %s,
                VL_TOTAL = %s,
                DISTANCIA_KM = %s,
                USUARIO = %s,
                DT_LANCAMENTO = NOW()
            WHERE ID_OF = %s AND ATIVO = 'S'
        """, (
            id_opa, id_controle, nu_sei, nome_passageiro, dt_emissao_sql,
            trecho, codigo_origem, codigo_destino, origem, destino,
            dt_embarque_sql, cia, localizador,
            vl_tarifa, vl_taxa_extra, vl_assento, vl_taxa_embarque, vl_total,
            distancia_km, usuario, id_of
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True, 'message': 'Passagem atualizada com sucesso!'})
    
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao atualizar passagem: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro ao atualizar: {str(e)}'}), 500


# ----- ROTA: EXCLUIR (INATIVAR) PASSAGEM -----
@app.route('/passagens/excluir/<int:id_of>', methods=['POST'])
@login_required
def passagens_excluir(id_of):
    try:
        cursor = mysql.connection.cursor()
        
        # Inativar ao invés de deletar
        cursor.execute("""
            UPDATE PASSAGENS_AEREAS_EMITIDAS 
            SET ATIVO = 'N' 
            WHERE ID_OF = %s
        """, (id_of,))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True, 'message': 'Passagem excluída com sucesso!'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro ao excluir: {str(e)}'}), 500


# ----- ROTA: FILTRAR PASSAGENS -----
@app.route('/passagens/filtrar', methods=['POST'])
@login_required
def passagens_filtrar():
    try:
        from datetime import datetime
        cursor = mysql.connection.cursor()
        
        # Receber ID_CONTROLE do formulário
        id_controle = request.form.get('id_controle', type=int)
        
        if not id_controle:
            return jsonify({'success': False, 'message': 'ID do contrato não informado'}), 400
        
        dt_inicio = request.form.get('dt_inicio_filtro')
        dt_fim = request.form.get('dt_fim_filtro')
        cia_filtro = request.form.get('cia_filtro')
        empenho_filtro = request.form.get('empenho_filtro')
        
        query = """
            SELECT 
                pae.ID_OF,
                pae.ID_OPA,
                pae.ID_CONTROLE,
                pae.NU_SEI,
                pae.NOME_PASSAGEIRO,
                DATE_FORMAT(pae.DT_EMISSAO, '%%d/%%m/%%Y') as DT_EMISSAO_F,
                pae.TRECHO,
                pae.CODIGO_ORIGEM,
                pae.CODIGO_DESTINO,
                CONCAT(ao.CODIGO_IATA, ' - ', ao.CIDADE, '/', ao.UF_ESTADO) as ORIGEM_FORMATADA,
                CONCAT(ad.CODIGO_IATA, ' - ', ad.CIDADE, '/', ad.UF_ESTADO) as DESTINO_FORMATADO,
                DATE_FORMAT(pae.DT_EMBARQUE, '%%d/%%m/%%Y') as DT_EMBARQUE_F,
                pae.CIA,
                pae.LOCALIZADOR,
                FORMAT(pae.VL_TARIFA, 2, 'de_DE') as VL_TARIFA_F,
                FORMAT(pae.VL_TAXA_EXTRA, 2, 'de_DE') as VL_TAXA_EXTRA_F,
                FORMAT(pae.VL_ASSENTO, 2, 'de_DE') as VL_ASSENTO_F,
                FORMAT(pae.VL_TAXA_EMBARQUE, 2, 'de_DE') as VL_TAXA_EMBARQUE_F,
                FORMAT(pae.VL_TOTAL, 2, 'de_DE') as VL_TOTAL_F,
                FORMAT(pae.DISTANCIA_KM, 2, 'de_DE') as DISTANCIA_KM_F,
                opa.NU_EMPENHO
            FROM PASSAGENS_AEREAS_EMITIDAS pae
            LEFT JOIN AEROPORTOS ao ON pae.CODIGO_ORIGEM = ao.CODIGO_IATA
            LEFT JOIN AEROPORTOS ad ON pae.CODIGO_DESTINO = ad.CODIGO_IATA
            LEFT JOIN ORCAMENTO_PASSAGENS_AEREAS opa ON pae.ID_OPA = opa.ID_OPA
            WHERE pae.ATIVO = 'S'
            AND pae.ID_CONTROLE = %s
        """
        
        params = [id_controle]
        
        if dt_inicio and dt_inicio.strip():
            query += " AND pae.DT_EMISSAO >= %s"
            params.append(dt_inicio)
        
        if dt_fim and dt_fim.strip():
            query += " AND pae.DT_EMISSAO <= %s"
            params.append(dt_fim)
        
        if cia_filtro and cia_filtro.strip():
            query += " AND pae.CIA = %s"
            params.append(cia_filtro)
        
        if empenho_filtro and empenho_filtro.strip():
            query += " AND opa.NU_EMPENHO = %s"
            params.append(empenho_filtro)
        
        query += " ORDER BY pae.ID_OF ASC"
        
        cursor.execute(query, tuple(params))
        passagens = cursor.fetchall()
        cursor.close()
        
        return jsonify({'success': True, 'data': passagens})
    
    except Exception as e:
        print(f"Erro ao filtrar passagens: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro ao filtrar: {str(e)}'}), 500


@app.route('/api/passagens/empenhos/periodo', methods=['GET'])
@login_required
def buscar_empenhos_por_periodo():
    """
    Retorna lista de empenhos distintos baseados no período de emissão e ID_CONTROLE
    """
    try:
        dt_inicio = request.args.get('dt_inicio')
        dt_fim = request.args.get('dt_fim')
        id_controle = request.args.get('id_controle', type=int)
        
        if not dt_inicio or not dt_fim:
            return jsonify({'success': False, 'message': 'Período não informado'}), 400
        
        if not id_controle:
            return jsonify({'success': False, 'message': 'ID do contrato não informado'}), 400
        
        cursor = mysql.connection.cursor()
        
        query = """
            SELECT DISTINCT opa.NU_EMPENHO
            FROM PASSAGENS_AEREAS_EMITIDAS pae
            INNER JOIN ORCAMENTO_PASSAGENS_AEREAS opa ON pae.ID_OPA = opa.ID_OPA
            WHERE pae.ATIVO = 'S'
            AND pae.ID_CONTROLE = %s
            AND pae.DT_EMISSAO >= %s
            AND pae.DT_EMISSAO <= %s
            AND opa.NU_EMPENHO IS NOT NULL
            AND opa.NU_EMPENHO != ''
            ORDER BY opa.NU_EMPENHO
        """
        
        cursor.execute(query, (id_controle, dt_inicio, dt_fim))
        rows = cursor.fetchall()
        cursor.close()
        
        empenhos = [row[0] for row in rows]
        
        return jsonify({
            'success': True,
            'empenhos': empenhos
        })
        
    except Exception as e:
        print(f"Erro ao buscar empenhos: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Erro ao buscar empenhos: {str(e)}'}), 500


# ----- ROTA: BUSCAR ORÇAMENTOS DISPONÍVEIS PARA SELEÇÃO -----
@app.route('/api/orcamento/passagens/disponiveis', methods=['GET'])
@login_required
def listar_orcamentos_disponiveis():
    """
    Retorna lista de orçamentos com saldo disponível para vincular passagens
    """
    try:
        cursor = mysql.connection.cursor()
        
        query = """
            SELECT 
                opa.ID_OPA,
                opa.UO,
                opa.UNIDADE,
                p.ID_PROGRAMA,
                p.DE_PROGRAMA,
                CONCAT(si.ID_SUBITEM, ' - ', si.DE_SUBITEM) as SUBITEM,
                opa.VL_APROVADO,
                COALESCE(SUM(CASE WHEN pae.ATIVO = 'S' THEN pae.VL_TOTAL ELSE 0 END), 0) as VL_UTILIZADO,
                (opa.VL_APROVADO - COALESCE(SUM(CASE WHEN pae.ATIVO = 'S' THEN pae.VL_TOTAL ELSE 0 END), 0)) as SALDO,
                opa.NU_EMPENHO,
                opa.EXERCICIO
            FROM ORCAMENTO_PASSAGENS_AEREAS opa
            LEFT JOIN PROGRAMA_ORCAMENTO p ON opa.ID_PROGRAMA = p.ID_PROGRAMA
            LEFT JOIN SUBITEM_ORCAMENTO si ON opa.ID_SUBITEM = si.ID_SUBITEM
            LEFT JOIN PASSAGENS_AEREAS_EMITIDAS pae ON opa.ID_OPA = pae.ID_OPA AND pae.ATIVO = 'S'
            WHERE opa.ATIVO = 'S'
            GROUP BY 
                opa.ID_OPA,
                opa.UO,
                opa.UNIDADE,
                p.ID_PROGRAMA,
                p.DE_PROGRAMA,
                si.ID_SUBITEM,
                si.DE_SUBITEM,
                opa.VL_APROVADO,
                opa.NU_EMPENHO,
                opa.EXERCICIO
            HAVING SALDO > 0
            ORDER BY opa.EXERCICIO DESC, opa.ID_OPA DESC
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        registros = []
        for row in rows:
            # Formatar programa completo: ID - DESCRIÇÃO
            programa_completo = f"{row[3]} - {row[4]}" if row[3] and row[4] else ''
            
            registro = {
                'id_opa': row[0],
                'uo': row[1] or '',
                'unidade': row[2] or '',
                'programa': programa_completo,
                'subitem': row[5] or '',
                'vl_aprovado': float(row[6]) if row[6] else 0.0,
                'vl_utilizado': float(row[7]) if row[7] else 0.0,
                'saldo': float(row[8]) if row[8] else 0.0,
                'nu_empenho': row[9] or '',
                'exercicio': row[10]
            }
            registros.append(registro)
        
        cursor.close()
        
        return jsonify({
            'success': True,
            'registros': registros
        })
        
    except Exception as e:
        print(f"Erro ao listar orçamentos disponíveis: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ----- ROTA: BUSCAR LISTA DE PASSAGEIROS CADASTRADOS -----
@app.route('/api/passageiros/listar', methods=['GET'])
@login_required
def listar_passageiros():
    """
    Retorna lista de passageiros únicos já cadastrados no sistema
    para autocomplete
    """
    try:
        cursor = mysql.connection.cursor()
        
        query = """
            SELECT DISTINCT NOME_PASSAGEIRO 
            FROM PASSAGENS_AEREAS_EMITIDAS 
            WHERE ATIVO = 'S' 
            AND NOME_PASSAGEIRO IS NOT NULL 
            AND NOME_PASSAGEIRO != ''
            ORDER BY NOME_PASSAGEIRO
        """
        
        cursor.execute(query)
        passageiros = [row[0] for row in cursor.fetchall()]
        cursor.close()
        
        return jsonify({
            'success': True,
            'passageiros': passageiros
        })
        
    except Exception as e:
        print(f"Erro ao listar passageiros: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
		

###############

def validar_aeroportos_no_banco(codigos_possiveis, cursor):
    """
    Valida uma lista de códigos IATA contra a tabela AEROPORTOS
    Retorna apenas os códigos que existem no banco
    
    Args:
        codigos_possiveis: Lista de códigos de 3 letras para validar
        cursor: Cursor do MySQL
    
    Returns:
        Lista de códigos válidos (que existem no banco)
    """
    if not codigos_possiveis:
        return []
    
    # Remove duplicatas mantendo ordem
    codigos_unicos = []
    for codigo in codigos_possiveis:
        if codigo not in codigos_unicos:
            codigos_unicos.append(codigo)
    
    # Monta query com placeholders
    placeholders = ','.join(['%s'] * len(codigos_unicos))
    query = f"""
        SELECT CODIGO_IATA 
        FROM AEROPORTOS 
        WHERE CODIGO_IATA IN ({placeholders})
        AND ATIVO = 'S'
        ORDER BY FIELD(CODIGO_IATA, {placeholders})
    """
    
    # Parâmetros: códigos duas vezes (para IN e ORDER BY FIELD)
    params = codigos_unicos + codigos_unicos
    
    cursor.execute(query, params)
    resultados = cursor.fetchall()
    
    # Retorna lista de códigos válidos
    return [row[0] for row in resultados]

# Criar pasta de upload se não existir
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# def allowed_file(filename):
#     return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def converter_valor_br(valor_str):
    """Converte valor brasileiro (1.234,56) para float"""
    if not valor_str:
        return 0.0
    # Remove pontos (milhares) e troca vírgula por ponto
    valor_limpo = valor_str.replace('.', '').replace(',', '.')
    return float(valor_limpo)


def validar_aeroportos_no_banco_sem_remover_duplicatas(codigos_possiveis, cursor):
    """
    Valida códigos IATA no banco MANTENDO A ORDEM E DUPLICATAS
    Remove apenas duplicatas CONSECUTIVAS (ex: VCP VCP → VCP)
    
    Args:
        codigos_possiveis: Lista de códigos ['JPR', 'VCP', 'VCP', 'POA', 'POA', 'VCP', 'VCP', 'JPR']
        cursor: Cursor do MySQL
    
    Returns:
        Lista: ['JPR', 'VCP', 'POA', 'VCP', 'JPR'] (sem duplicatas consecutivas)
    """
    if not codigos_possiveis:
        return []
    
    # Remove duplicatas CONSECUTIVAS primeiro
    # ['JPR', 'VCP', 'VCP', 'POA'] → ['JPR', 'VCP', 'POA']
    codigos_sem_consecutivos = []
    anterior = None
    for codigo in codigos_possiveis:
        if codigo != anterior:
            codigos_sem_consecutivos.append(codigo)
            anterior = codigo
    
    print(f"🔍 Códigos após remover consecutivos: {codigos_sem_consecutivos}")
    
    # Pegar códigos únicos para consultar banco (otimização)
    codigos_unicos = list(set(codigos_sem_consecutivos))
    
    # Consultar banco
    if not codigos_unicos:
        return []
    
    placeholders = ','.join(['%s'] * len(codigos_unicos))
    query = f"""
        SELECT CODIGO_IATA 
        FROM AEROPORTOS 
        WHERE CODIGO_IATA IN ({placeholders})
        AND ATIVO = 'S'
    """
    
    cursor.execute(query, codigos_unicos)
    resultados = cursor.fetchall()
    
    # Set de códigos válidos no banco
    codigos_validos_set = {row[0] for row in resultados}
    
    # Filtrar mantendo ordem e removendo inválidos
    aeroportos_validos = [
        codigo for codigo in codigos_sem_consecutivos 
        if codigo in codigos_validos_set
    ]
    
    return aeroportos_validos


def validar_aeroportos_no_banco_robusto(codigos_possiveis, cursor):
    """
    Valida códigos no banco MAS mantém os não encontrados se fizerem sentido
    
    Args:
        codigos_possiveis: ['JPR', 'VCP', 'POA', 'VCP', 'JPR']
        cursor: Cursor MySQL
    
    Returns:
        Lista mantendo códigos válidos + códigos de 3 letras mesmo não no banco
    """
    if not codigos_possiveis:
        return []
    
    # 1. Remove duplicatas CONSECUTIVAS
    codigos_limpos = []
    anterior = None
    for codigo in codigos_possiveis:
        if codigo != anterior:
            codigos_limpos.append(codigo)
            anterior = codigo
    
    print(f"🔍 Após remover consecutivos: {codigos_limpos}")
    
    # 2. Pegar únicos para consultar banco
    codigos_unicos = list(set(codigos_limpos))
    
    if not codigos_unicos:
        return []
    
    # 3. Consultar banco
    placeholders = ','.join(['%s'] * len(codigos_unicos))
    query = f"""
        SELECT CODIGO_IATA 
        FROM AEROPORTOS 
        WHERE CODIGO_IATA IN ({placeholders})
        AND ATIVO = 'S'
    """
    
    cursor.execute(query, codigos_unicos)
    resultados = cursor.fetchall()
    
    # Set de códigos ENCONTRADOS no banco
    codigos_no_banco = {row[0] for row in resultados}
    print(f"✅ Códigos encontrados no banco: {codigos_no_banco}")
    
    # 4. SOLUÇÃO ROBUSTA: Manter TODOS os códigos de 3 letras válidos
    # Mesmo que não estejam no banco (pode ser aeroporto novo/regional)
    aeroportos_validos = []
    codigos_nao_encontrados = []
    
    for codigo in codigos_limpos:
        if codigo in codigos_no_banco:
            # Está no banco - adiciona
            aeroportos_validos.append(codigo)
        elif len(codigo) == 3 and codigo.isalpha() and codigo.isupper():
            # Não está no banco MAS é um código IATA válido (3 letras)
            # ADICIONA MESMO ASSIM com warning
            aeroportos_validos.append(codigo)
            codigos_nao_encontrados.append(codigo)
    
    if codigos_nao_encontrados:
        print(f"⚠️ Aeroportos NÃO encontrados no banco (mas válidos): {codigos_nao_encontrados}")
        print(f"   💡 Considere adicionar ao banco: {', '.join(codigos_nao_encontrados)}")
    
    return aeroportos_validos

# ============================================================================
# EXTRAÇÃO DE LOCALIZADOR - VERSÃO FINAL LIMPA
# ============================================================================

def extrair_localizador_modelo1(texto):
    """
    Extrai localizador do Modelo 1
    
    LÓGICA:
    1. Tenta Bilhetes (5-7 chars)
    2. Se código em Reservas > 7 chars, IGNORA e busca em Trechos
    3. Em Trechos: junta linhas do voo e pega últimos 6 caracteres alfabéticos
    """
    
    localizador = ''
    
    # ====================================================================
    # MÉTODO 1: Bilhetes (5-7 chars)
    # ====================================================================
    
    match_loc = re.search(
        r'Eticket\s+Localizador.*?\d{10,}\s+([A-Z0-9]{5,7})\s+', 
        texto, 
        re.DOTALL
    )
    
    if match_loc:
        localizador = match_loc.group(1)
        print(f"✅ Localizador (Bilhetes): {localizador}")
        return localizador
    
    # ====================================================================
    # VERIFICAR: Código longo em Reservas?
    # ====================================================================
    
    match_reservas_longo = re.search(
        r'Localizador\s+Trecho.*?\n\s*([A-Z0-9]{8,})\s+',
        texto,
        re.DOTALL
    )
    
    if match_reservas_longo:
        codigo_longo = match_reservas_longo.group(1)
        print(f"⚠️ Código longo em Reservas ({len(codigo_longo)} chars): {codigo_longo}")
        print(f"   → IGNORANDO, buscando em Trechos...")
    
    # ====================================================================
    # MÉTODO 2: Trechos - Últimos 6 caracteres alfabéticos
    # ====================================================================
    
    print("🔍 Buscando em Trechos...")
    
    match_trechos = re.search(r'Trechos(.*?)Bilhetes', texto, re.DOTALL)
    
    if match_trechos:
        texto_trechos = match_trechos.group(1)
        linhas = texto_trechos.split('\n')
        
        # Procurar linha com código de voo e juntar linhas seguintes
        linha_completa = ''
        achou_voo = False
        
        for linha in linhas:
            if not achou_voo:
                # Buscar LA 3014, AD 4681, G3 1234, etc
                if re.search(r'(LA|AD|G3)[\s-]*\d{3,4}', linha, re.IGNORECASE):
                    achou_voo = True
                    linha_completa = linha
                    print(f"   ✅ Linha do voo encontrada")
            elif achou_voo:
                # Juntar linhas até encontrar linha vazia
                if linha.strip() == '':
                    break
                else:
                    linha_completa += ' ' + linha
        
        if linha_completa:
            # Extrair TODOS os caracteres alfabéticos
            apenas_letras = re.findall(r'[A-Z]', linha_completa)
            
            print(f"   📊 Total de letras na linha: {len(apenas_letras)}")
            
            if len(apenas_letras) >= 6:
                # Pegar os 6 ÚLTIMOS
                localizador = ''.join(apenas_letras[-6:])
                print(f"   ✅ Localizador (últimos 6): {localizador}")
                return localizador
    
    # ====================================================================
    # FALLBACK (NÃO DEVERIA CHEGAR AQUI)
    # ====================================================================
    
    if not localizador and match_reservas_longo:
        codigo_longo = match_reservas_longo.group(1)
        localizador = codigo_longo[-6:]
        print(f"⚠️ FALLBACK - usando últimos 6 de Reservas: {localizador}")
        print(f"   ⚠️ ISTO NÃO DEVERIA ACONTECER!")
        return localizador
    
    if not localizador:
        print("❌ Localizador NÃO encontrado")
    
    return localizador


# ============================================================================
# FUNÇÃO PRINCIPAL ATUALIZADA
# ============================================================================

def extrair_dados_bilhete_modelo1(texto, cursor):
    """Extrai dados do bilhete modelo 1 - COM LOCALIZADOR MELHORADO"""
    dados = {
        'dt_emissao': '',
        'nu_sei': '',
        'nome_passageiro': '',
        'localizador': '',
        'trecho': '',
        'origem': '',
        'destino': '',
        'cia': '',
        'vl_tarifa': '',
        'vl_taxa_extra': '',
        'vl_total': '',
        'dt_embarque': ''
    }
    
    try:
        print("=" * 80)
        print("EXTRAINDO DADOS - MODELO 1")
        print("=" * 80)
        
        texto_limpo = texto.replace('\n', ' ')
        
        # 1. DATA DE EMISSÃO
        match_data = re.search(r'Data:\s*(\d{2}/\d{2}/\d{4})', texto)
        if match_data:
            dados['dt_emissao'] = match_data.group(1)
            print(f"✅ Data Emissão: {dados['dt_emissao']}")
        
        # 2. Nº SEI
        match_sei = re.search(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', texto)
        if match_sei:
            dados['nu_sei'] = match_sei.group(0)
            print(f"✅ Nº SEI: {dados['nu_sei']}")
        
        # 3. NOME DO PASSAGEIRO
        match_nome = re.search(r'Nome\s+Sobrenome.*?([A-Z\s]+?)\s+ADT', texto, re.DOTALL)
        if match_nome:
            nome_bruto = match_nome.group(1).strip()
            nome_limpo = re.sub(r'\s+Tipo\s+', ' ', nome_bruto)
            nome_limpo = re.sub(r'\s+Sexo\s+', ' ', nome_limpo)
            nome_limpo = re.sub(r'\s+Assentos\s+', ' ', nome_limpo)
            nome_limpo = ' '.join(nome_limpo.split())
            nome_limpo = re.sub(r'\s+\d+$', '', nome_limpo)
            dados['nome_passageiro'] = capitalizar_nome(nome_limpo)
            print(f"✅ Nome: {dados['nome_passageiro']}")
        
        # 4. LOCALIZADOR - MÉTODO MELHORADO (3 tentativas)
        print("\n🔍 BUSCANDO LOCALIZADOR...")
        dados['localizador'] = extrair_localizador_modelo1(texto)
        
        # 5. TRECHO (mesmo código anterior com detecção ida/volta)
        print("\n🔍 BUSCANDO TRECHO...")
        
        match_trecho = re.search(
            r'([A-Z]{3}\s*-\s*[A-Z]{3}(?:\s*/\s*[A-Z]{3}\s*-\s*[A-Z]{3})*)',
            texto_limpo
        )
        
        if match_trecho:
            trecho_bruto = match_trecho.group(1)
            print(f"📍 Trecho BRUTO: '{trecho_bruto}'")
            
            trecho_limpo = trecho_bruto.replace(' ', '')
            print(f"📍 Trecho LIMPO: '{trecho_limpo}'")
            
            codigos_trecho = re.findall(r'([A-Z]{3})', trecho_limpo)
            print(f"📍 Códigos extraídos: {codigos_trecho}")
            
            # Validação robusta (mantém códigos mesmo não no banco)
            aeroportos_validos = validar_aeroportos_no_banco_robusto(
                codigos_trecho, cursor
            )
            print(f"✅ Aeroportos validados: {aeroportos_validos}")
            
            if aeroportos_validos:
                resultado = detectar_origem_destino_ida_volta(aeroportos_validos)
                
                dados['origem'] = resultado['origem']
                dados['destino'] = resultado['destino']
                
                print(f"\n✅ Origem: {dados['origem']}")
                print(f"✅ Destino: {dados['destino']}")
                
                if resultado['ida_volta']:
                    print(f"✈️ IDA E VOLTA")
                
                trechos = []
                for i in range(len(aeroportos_validos) - 1):
                    trechos.append(f"{aeroportos_validos[i]}-{aeroportos_validos[i+1]}")
                dados['trecho'] = '/'.join(trechos)
                
                print(f"✅ Trecho: {dados['trecho']}")
        
        # 6. COMPANHIA AÉREA
        for cia in ['AZUL', 'GOL', 'LATAM']:
            if cia in texto:
                dados['cia'] = cia
                print(f"✅ CIA: {dados['cia']}")
                break
        
        # 7. VALORES
        match_valores = re.search(
            r'Tarifa\s+Taxas\s+Total.*?R\$\s*([\d.,]+)\s*R\$\s*([\d.,]+)\s*R\$\s*([\d.,]+)',
            texto,
            re.DOTALL
        )
        if match_valores:
            dados['vl_tarifa'] = match_valores.group(1)
            dados['vl_taxa_extra'] = match_valores.group(2)
            dados['vl_total'] = match_valores.group(3)
            print(f"✅ Tarifa: {dados['vl_tarifa']}")
        
        # 8. DATA DE EMBARQUE
        match_embarque = re.search(r'Saída.*?(\d{2}/\d{2}/\d{4})', texto, re.DOTALL)
        if match_embarque:
            dados['dt_embarque'] = match_embarque.group(1)
            print(f"✅ Data Embarque: {dados['dt_embarque']}")
        
        print("=" * 80 + "\n")
        
    except Exception as e:
        print(f"❌ Erro: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return dados


def remover_acentos(texto):
    """Remove acentos de um texto para comparação"""
    if not texto:
        return texto
    # Normaliza para NFD (separa caracteres base de acentos)
    nfkd = unicodedata.normalize('NFD', texto)
    # Remove caracteres de acento (categoria Mn = Nonspacing Mark)
    sem_acento = ''.join([c for c in nfkd if not unicodedata.combining(c)])
    return sem_acento


def extrair_trechos_modelo2_ida_volta(texto, cursor):
    """
    Extrai trechos do Modelo 2 com detecção de IDA E VOLTA
    
    LÓGICA:
    - Se linha seguinte tem "Conexão em:" → continuação do mesmo sentido
    - Se linha seguinte TEM voo MAS NÃO tem "Conexão em:" → início da VOLTA
    """
    
    print("\n🔍 EXTRAINDO TRECHOS COM DETECÇÃO DE VOLTA...")
    
    # Extrair seção Voos
    match_voos = re.search(
        r'Voos(.*?)(?:Mochila ou bolsa|Assentos|Valores|Bilhetes|$)', 
        texto, 
        re.DOTALL
    )
    
    if not match_voos:
        print("❌ Seção Voos não encontrada!")
        return []
    
    texto_voos = match_voos.group(1)
    
    # Remover acentos para facilitar busca
    texto_voos_sem_acento = remover_acentos(texto_voos)
    
    print(f"📄 Texto voos (primeiros 200): {texto_voos_sem_acento[:200]}...")
    
    # Extrair TODAS as linhas de voo
    # Padrão: XXX - CIDADE ... XXX - CIDADE (origem e destino na mesma linha)
    padrao_linha_voo = r'([A-Z]{3})\s*-\s*([A-Z\s]+?)\s+\d{2}\s+\w{3}\s+\d{4}.*?([A-Z]{3})\s*-\s*([A-Z\s]+?)\s+\d{2}\s+\w{3}\s+\d{4}'
    
    linhas_voo = re.finditer(padrao_linha_voo, texto_voos_sem_acento)
    
    trechos_info = []
    posicoes = []
    
    for match in linhas_voo:
        origem_cod = match.group(1).strip()
        origem_cidade = match.group(2).strip()
        destino_cod = match.group(3).strip()
        destino_cidade = match.group(4).strip()
        
        # Correção POR → PVH
        if origem_cod == 'POR':
            origem_cod = 'PVH'
        if destino_cod == 'POR':
            destino_cod = 'PVH'
        
        posicao_inicio = match.start()
        posicoes.append(posicao_inicio)
        
        trechos_info.append({
            'origem': origem_cod,
            'destino': destino_cod,
            'posicao': posicao_inicio
        })
        
        print(f"   📍 Voo encontrado: {origem_cod}-{destino_cod}")
    
    if not trechos_info:
        print("❌ Nenhum voo encontrado!")
        return []
    
    print(f"\n📊 Total de voos: {len(trechos_info)}")
    
    # Agora detectar onde está a VOLTA
    # Procurar por cada voo se tem "Conexão em:" entre ele e o próximo
    
    codigos_finais = []
    
    for i, trecho in enumerate(trechos_info):
        # Adicionar origem (se ainda não foi adicionada)
        if not codigos_finais or codigos_finais[-1] != trecho['origem']:
            codigos_finais.append(trecho['origem'])
        
        # Adicionar destino
        codigos_finais.append(trecho['destino'])
        
        # Verificar se tem "Conexão em:" entre este voo e o próximo
        if i + 1 < len(trechos_info):
            pos_atual = trecho['posicao']
            pos_proxima = trechos_info[i + 1]['posicao']
            
            # Texto entre os dois voos
            texto_entre = texto_voos_sem_acento[pos_atual:pos_proxima]
            
            tem_conexao = 'CONEXAO EM:' in texto_entre or 'CONEXÃO EM:' in texto_entre
            
            if tem_conexao:
                print(f"   ✅ Conexão detectada após {trecho['origem']}-{trecho['destino']}")
            else:
                print(f"   🔄 SEM conexão após {trecho['origem']}-{trecho['destino']} → Próximo é VOLTA")
    
    print(f"\n📍 Códigos na ordem: {codigos_finais}")
    
    return codigos_finais
    

def validar_aeroportos_no_banco_modelo2(codigos_possiveis, cursor):
    """Mesma função"""
    if not codigos_possiveis:
        return []
    
    # Remove consecutivos
    codigos_limpos = []
    anterior = None
    for codigo in codigos_possiveis:
        if codigo != anterior:
            codigos_limpos.append(codigo)
            anterior = codigo
    
    print(f"🔍 Após remover consecutivos: {codigos_limpos}")
    
    # Consulta banco (implementar)
    # Por enquanto retorna todos como válidos
    return codigos_limpos

def extrair_dados_bilhete_modelo2(texto, cursor):
    """
    Extrai dados do bilhete Modelo 2 (Portal) - VERSÃO FINAL
    COM DETECÇÃO DE IDA E VOLTA
    """
    dados = {
        'dt_emissao': '',
        'nu_sei': '',
        'nome_passageiro': '',
        'localizador': '',
        'trecho': '',
        'origem': '',
        'destino': '',
        'cia': '',
        'vl_tarifa': '',
        'vl_taxa_extra': '',
        'vl_total': '',
        'dt_embarque': ''
    }
    
    try:
        print("=" * 80)
        print("EXTRAINDO DADOS - MODELO 2 (VERSÃO FINAL COM IDA/VOLTA)")
        print("=" * 80)
                
       # 1. LOCALIZADOR
        match_loc = re.search(
            r'Localizador.*?\n(.+?)(?:Emitido|Status|Passageiros)',
            texto,
            re.DOTALL
        )
        if match_loc:
            bloco_loc = match_loc.group(1)
            bloco_limpo = re.sub(r'[-\s]+', ' ', bloco_loc)
            codigos = re.findall(r'([A-Z0-9]{6,})', bloco_limpo)
           
            if len(codigos) == 1:
                codigo = codigos[0]
                if len(codigo) == 6:
                    dados['localizador'] = codigo
                elif len(codigo) > 6:
                    dados['localizador'] = codigo[-6:]
            elif len(codigos) >= 2:
                for cod in codigos:
                    if len(cod) == 6:
                        dados['localizador'] = cod
                        break
                if not dados['localizador'] and codigos:
                    dados['localizador'] = codigos[0][-6:]
           
            if dados['localizador']:
                print(f"✅ Localizador: {dados['localizador']}")

        # 2. NOME
        match_nome = re.search(
            r'Sobrenome\s+Nome.*?\n.*?([A-Z]+)\s+([A-Z\s]+?)\s+(?:Masculino|Feminino)',
            texto,
            re.DOTALL
        )
        if match_nome:
            sobrenome = match_nome.group(1).strip()
            nome = match_nome.group(2).strip()
            nome_completo = f"{nome} {sobrenome}"
            dados['nome_passageiro'] = capitalizar_nome(nome_completo)
            print(f"✅ Nome: {dados['nome_passageiro']}")
        
        # 3. CIA
        if 'LATAM' in texto or 'Latam' in texto:
            dados['cia'] = 'LATAM'
        elif 'AZUL' in texto or 'Azul' in texto:
            dados['cia'] = 'AZUL'
        elif 'GOL' in texto:
            dados['cia'] = 'GOL'
        
        if dados['cia']:
            print(f"✅ CIA: {dados['cia']}")
        
        # 4. TRECHOS - NOVA LÓGICA
        codigos_ordem = extrair_trechos_modelo2_ida_volta(texto, cursor)
        
        if codigos_ordem:
            # Remover duplicatas CONSECUTIVAS
            codigos_limpos = []
            anterior = None
            for cod in codigos_ordem:
                if cod != anterior:
                    codigos_limpos.append(cod)
                    anterior = cod
            
            print(f"📍 Após remover consecutivos: {codigos_limpos}")
            
            # Detectar origem/destino
            if len(codigos_limpos) >= 2:
                resultado = detectar_origem_destino_ida_volta(codigos_limpos)
                
                dados['origem'] = resultado['origem']
                dados['destino'] = resultado['destino']
                
                print(f"\n✅ Origem: {dados['origem']}")
                print(f"✅ Destino: {dados['destino']}")
                
                if resultado['ida_volta']:
                    print(f"✈️ IDA E VOLTA detectado!")
                
                # Reconstrói trecho
                trechos = []
                for i in range(len(codigos_limpos) - 1):
                    trechos.append(f"{codigos_limpos[i]}-{codigos_limpos[i+1]}")
                dados['trecho'] = '/'.join(trechos)
                
                print(f"✅ Trecho: {dados['trecho']}")
        
        # 5. DATA EMBARQUE
        match_data_voo = re.search(r'(\d{2})\s+(\w{3})\s+(\d{4})', texto)
        if match_data_voo:
            dia = match_data_voo.group(1)
            mes_texto = match_data_voo.group(2).upper()
            ano = match_data_voo.group(3)
            
            meses = {
                'JAN': '01', 'FEV': '02', 'MAR': '03', 'ABR': '04',
                'MAI': '05', 'JUN': '06', 'JUL': '07', 'AGO': '08',
                'SET': '09', 'OUT': '10', 'NOV': '11', 'DEZ': '12'
            }
            
            mes = meses.get(mes_texto[:3], '01')
            dados['dt_embarque'] = f"{dia}/{mes}/{ano}"
            print(f"✅ Data Embarque: {dados['dt_embarque']}")
        
        # 6. DATA EMISSÃO
        match_emissao = re.search(r'Data Emissão\s*(\d{2}/\d{2}/\d{4})', texto)
        if not match_emissao:
            match_emissao = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
        if match_emissao:
            dados['dt_emissao'] = match_emissao.group(1)
            print(f"✅ Data Emissão: {dados['dt_emissao']}")
        
        # 7. VALORES
        valores = re.findall(r'R\$\s*([\d.,]+)', texto)
        if len(valores) >= 3:
            dados['vl_tarifa'] = valores[0]
            dados['vl_taxa_extra'] = valores[1]
            dados['vl_total'] = valores[2]
            
            print(f"✅ Tarifa: {dados['vl_tarifa']}")
            print(f"✅ Taxas: {dados['vl_taxa_extra']}")
            print(f"✅ Total: {dados['vl_total']}")
        
        print("=" * 80 + "\n")
        
    except Exception as e:
        print(f"❌ Erro: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return dados


def detectar_origem_destino_ida_volta(aeroportos_validados):
    """Detecta ida e volta"""
    if not aeroportos_validados or len(aeroportos_validados) < 2:
        return {'origem': '', 'destino': '', 'ida_volta': False}
    
    origem = aeroportos_validados[0]
    ultimo = aeroportos_validados[-1]
    
    if origem == ultimo and len(aeroportos_validados) >= 3:
        indice_meio = len(aeroportos_validados) // 2
        destino = aeroportos_validados[indice_meio]
        return {'origem': origem, 'destino': destino, 'ida_volta': True}
    else:
        destino = aeroportos_validados[-1]
        return {'origem': origem, 'destino': destino, 'ida_volta': False}
    

def capitalizar_nome(nome):
    """Converte NOME COMPLETO para Nome Completo"""
    if not nome:
        return nome
    
    nome = ' '.join(nome.split())
    
    minusculas = ['de', 'da', 'do', 'dos', 'das', 'e', 'a', 'o', 'as', 'os']
    palavras = nome.lower().split()
    resultado = []
    
    for i, palavra in enumerate(palavras):
        if i == 0 or palavra not in minusculas:
            resultado.append(palavra.capitalize())
        else:
            resultado.append(palavra)
    
    return ' '.join(resultado)


def limpar_cia(cia_texto):
    """Limpa o nome da companhia aérea"""
    if not cia_texto:
        return ''
    
    cia = cia_texto.strip()
    
    # Remove códigos IATA e caracteres extras
    cia = re.sub(r'\s+[A-Z]{2}$', '', cia)  # Remove código de 2 letras no final
    cia = re.sub(r'^[A-Z]{2}\s*-\s*', '', cia)  # Remove código no início
    
    # Padroniza nomes conhecidos
    if 'LATAM' in cia.upper():
        return 'LATAM'
    elif 'GOL' in cia.upper():
        return 'GOL'
    elif 'AZUL' in cia.upper():
        return 'AZUL'
    
    return cia.strip().upper()


# ============================================================================
# SISTEMA COMPLETO COM DETECÇÃO AUTOMÁTICA DE MODELO DE BILHETE
# ============================================================================
# Substitua a rota /passagens/upload_bilhete no seu app.py por esta versão


@app.route('/passagens/upload_bilhete', methods=['POST'])
@login_required
def passagens_upload_bilhete():
    """Processa upload do PDF do bilhete e extrai dados - VERSÃO COM BD"""
    
    cursor = None
    
    try:
        if 'bilhete_pdf' not in request.files:
            return jsonify({'success': False, 'message': 'Nenhum arquivo enviado'}), 400
        
        file = request.files['bilhete_pdf']
        
        if file.filename == '':
            return jsonify({'success': False, 'message': 'Arquivo sem nome'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': 'Apenas arquivos PDF são permitidos'}), 400
        
        # Salvar arquivo temporariamente
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        
        # Extrair texto do PDF
        texto_completo = ''
        with open(filepath, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            for page in pdf_reader.pages:
                texto_completo += page.extract_text()
        
        # Remover arquivo temporário
        os.remove(filepath)
        
        # Criar cursor para consultas ao banco
        cursor = mysql.connection.cursor()
        
        # Detecção automática do modelo
        modelo = identificar_modelo_bilhete(texto_completo)
        print(f"📄 Modelo detectado: {modelo}")
        
        # Extrair dados conforme o modelo (PASSA O CURSOR!)
        if modelo == 2:
            dados = extrair_dados_bilhete_modelo2(texto_completo, cursor)
        else:
            dados = extrair_dados_bilhete_modelo1(texto_completo, cursor)
        
        # Fechar cursor
        cursor.close()
        cursor = None
        
        # Verificar se conseguiu extrair dados
        dados_extraidos = sum(1 for v in dados.values() if v)
        
        if dados_extraidos == 0:
            return jsonify({
                'success': False, 
                'message': 'Não foi possível extrair dados do bilhete.'
            }), 400
        
        return jsonify({
            'success': True, 
            'message': f'{dados_extraidos} campos extraídos! (Modelo {modelo})',
            'data': dados,
            'modelo': modelo
        })
    
    except Exception as e:
        if cursor:
            cursor.close()
        
        print(f"❌ Erro: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False, 
            'message': f'Erro ao processar arquivo: {str(e)}'
        }), 500


def identificar_modelo_bilhete(texto):
    """Identifica automaticamente o modelo do bilhete"""
    if 'Portal do Agente' in texto or 'Reserva Aérea - Plano de Viagem' in texto:
        return 2
    if 'Wooba' in texto or re.search(r'OS:\s*\d{6}', texto):
        return 1
    return 1  # Padrão


# ============================================================================
# FUNÇÃO AUXILIAR: CALCULAR DISTÂNCIA ENTRE AEROPORTOS
# ============================================================================
def calcular_distancia_aeroportos(codigo_origem, codigo_destino):
    """
    Calcula distância entre dois aeroportos usando fórmula Haversine
    
    Args:
        codigo_origem: Código IATA do aeroporto de origem (ex: 'PVH')
        codigo_destino: Código IATA do aeroporto de destino (ex: 'BSB')
    
    Returns:
        Distância em quilômetros (float)
    """
    try:
        # Buscar coordenadas dos aeroportos
        origem = airports.get(codigo_origem.upper())
        destino = airports.get(codigo_destino.upper())
        
        if not origem or not destino:
            raise ValueError(f"Aeroporto não encontrado: {codigo_origem} ou {codigo_destino}")
        
        # Coordenadas (latitude e longitude)
        lat1, lon1 = origem['lat'], origem['lon']
        lat2, lon2 = destino['lat'], destino['lon']
        
        # Fórmula de Haversine para calcular distância entre dois pontos na Terra
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
        
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        # Raio da Terra em quilômetros
        raio_terra_km = 6371
        
        distancia_km = raio_terra_km * c
        
        return round(distancia_km, 2)
        
    except Exception as e:
        print(f"Erro ao calcular distância {codigo_origem}-{codigo_destino}: {str(e)}")
        raise


# ============================================================================
# ROTA 1: DISTÂNCIA SIMPLES ENTRE DOIS AEROPORTOS
# ============================================================================
@app.route('/distancia_aeroportos', methods=['GET'])
def distancia_aeroportos():
    """
    Calcula distância entre dois aeroportos
    Exemplo: /distancia_aeroportos?origem=PVH&destino=BSB
    """
    origem = request.args.get('origem', '').upper()
    destino = request.args.get('destino', '').upper()

    if origem and destino:
        try:
            km = calcular_distancia_aeroportos(origem, destino)
            return jsonify({'distancia_km': km})
        except ValueError as e:
            return jsonify({'erro': str(e)}), 404
        except Exception as e:
            return jsonify({'erro': f'Erro ao calcular: {str(e)}'}), 500

    return jsonify({'erro': 'Informe origem e destino (ex: ?origem=PVH&destino=GRU)'}), 400


# ============================================================================
# ROTA 2: CALCULAR DISTÂNCIA TOTAL DO TRECHO (COM CONEXÕES)
# ============================================================================
@app.route('/calcular_distancia_trecho', methods=['GET'])
@login_required
def calcular_distancia_trecho():
    """
    Calcula a distância total de um trecho (com ou sem conexões)
    
    Exemplos:
    - /calcular_distancia_trecho?trecho=PVH-BSB
    - /calcular_distancia_trecho?trecho=POA-GRU/GRU-PVH
    
    Retorna:
    {
        "success": true,
        "distancia_total_km": 2500.45,
        "trechos": [
            {"origem": "POA", "destino": "GRU", "distancia_km": 850.30},
            {"origem": "GRU", "destino": "PVH", "distancia_km": 1650.15}
        ]
    }
    """
    try:
        trecho_completo = request.args.get('trecho', '').strip().upper()
        
        if not trecho_completo:
            return jsonify({
                'success': False,
                'error': 'Parâmetro trecho é obrigatório'
            }), 400
        
        # Validar formato do trecho
        # Padrão: XXX-XXX ou XXX-XXX/XXX-XXX/XXX-XXX/...
        import re
        padrao = r'^[A-Z]{3}-[A-Z]{3}(\/[A-Z]{3}-[A-Z]{3})*$'
        
        if not re.match(padrao, trecho_completo):
            return jsonify({
                'success': False,
                'error': 'Formato inválido! Use: XXX-XXX ou XXX-XXX/XXX-XXX',
                'exemplo': 'PVH-BSB ou POA-GRU/GRU-PVH'
            }), 400
        
        # Dividir trecho em segmentos
        # "POA-GRU/GRU-PVH" → ["POA-GRU", "GRU-PVH"]
        segmentos = trecho_completo.split('/')
        
        distancia_total = 0.0
        detalhes_trechos = []
        
        # Calcular distância de cada segmento
        for segmento in segmentos:
            # "POA-GRU" → ["POA", "GRU"]
            partes = segmento.split('-')
            
            if len(partes) != 2:
                return jsonify({
                    'success': False,
                    'error': f'Segmento inválido: {segmento}'
                }), 400
            
            origem = partes[0]
            destino = partes[1]
            
            # Calcular distância usando a função auxiliar
            try:
                km = calcular_distancia_aeroportos(origem, destino)
                
                distancia_total += km
                
                detalhes_trechos.append({
                    'origem': origem,
                    'destino': destino,
                    'distancia_km': km
                })
                
            except ValueError as e:
                return jsonify({
                    'success': False,
                    'error': f'Aeroporto não encontrado: {origem} ou {destino}',
                    'detalhes': 'Verifique se os códigos IATA são válidos'
                }), 404
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Erro ao calcular distância {origem}-{destino}: {str(e)}',
                    'detalhes': 'Erro interno ao calcular'
                }), 400
        
        # Retornar resultado
        return jsonify({
            'success': True,
            'trecho_completo': trecho_completo,
            'distancia_total_km': round(distancia_total, 2),
            'quantidade_trechos': len(segmentos),
            'trechos': detalhes_trechos
        })
        
    except Exception as e:
        print(f"Erro ao calcular distância do trecho: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': f'Erro interno: {str(e)}'
        }), 500


# ============================================================
# BLOCO 4: ROTAS /api/v2/ - CRIAR DEMANDA
# ============================================================

@app.route('/api/v2/agenda/demanda', methods=['POST'])
@login_required
def criar_demanda_v2():
    """
    NOVA VERSÃO com emissão WebSocket
    Cria demanda E notifica todos os clientes em tempo real
    """
    cursor = None
    try:
        data = request.get_json()
        cursor = mysql.connection.cursor()

        usuario = session.get('usuario_login')
        
        # Validações de conflito
        id_motorista = data.get('id_motorista')
        id_veiculo = data.get('id_veiculo')
        id_tipodemanda = data['id_tipodemanda']
        dt_inicio = data['dt_inicio']
        dt_fim = data['dt_fim']
        horario = data.get('horario')
        tem_horario = horario and horario.strip()
        
        # 1. Validar conflito de MOTORISTA
        if id_motorista and int(id_motorista) > 0:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM AGENDA_DEMANDAS
                WHERE ID_MOTORISTA = %s
                  AND DT_INICIO <= %s
                  AND DT_FIM >= %s
            """, (id_motorista, dt_fim, dt_inicio))
            
            if cursor.fetchone()[0] > 0:
                cursor.close()
                return jsonify({
                    'success': False,
                    'error': 'Este motorista já possui demanda(s) neste período.'
                }), 409
        
        # 2. Validar conflito de VEÍCULO
        if id_veiculo and not tem_horario:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM AGENDA_DEMANDAS
                WHERE ID_VEICULO = %s
                  AND DT_INICIO <= %s
                  AND DT_FIM >= %s
                  AND (HORARIO IS NULL OR HORARIO = '00:00:00')
            """, (id_veiculo, dt_fim, dt_inicio))
            
            if cursor.fetchone()[0] > 0:
                cursor.close()
                return jsonify({
                    'success': False,
                    'error': 'Este veículo já possui demanda(s) SEM horário neste período.'
                }), 409
        
        # Converter horário
        if tem_horario:
            horario_value = horario + ':00'
        else:
            horario_value = None
        
        # INSERIR DEMANDA
        cursor.execute("""
            INSERT INTO AGENDA_DEMANDAS 
            (ID_MOTORISTA, ID_TIPOVEICULO, ID_VEICULO, ID_TIPODEMANDA, 
             DT_INICIO, DT_FIM, SETOR, SOLICITANTE, DESTINO, NU_SEI, 
             OBS, SOLICITADO, HORARIO, TODOS_VEICULOS, NC_MOTORISTA, DT_LANCAMENTO, USUARIO)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
        """, (
            data.get('id_motorista'), 
            data.get('id_tipoveiculo'), 
            data.get('id_veiculo'),
            id_tipodemanda, 
            dt_inicio, 
            dt_fim,
            data.get('setor'), 
            data.get('solicitante'), 
            data.get('destino'), 
            data.get('nu_sei'),
            data.get('obs'),
            data.get('solicitado', 'N'),
            horario_value,
            data.get('todos_veiculos', 'N'),
            data.get('nc_motorista', ''),
            usuario
        ))
        
        mysql.connection.commit()
        id_ad = cursor.lastrowid
        
        # Gerenciar diária motorista atendimento
        gerenciar_diaria_motorista_atendimento(
            id_ad=id_ad,
            id_tipodemanda=id_tipodemanda,
            id_motorista=id_motorista,
            dt_inicio=dt_inicio,
            dt_fim=dt_fim,
            operacao='INSERT'
        )
        
        mysql.connection.commit()
        
        # BUSCAR DADOS COMPLETOS DA DEMANDA PARA EMITIR
        cursor.execute("""
            SELECT ae.ID_AD, ae.ID_MOTORISTA, 
                   CASE 
                       WHEN ae.ID_MOTORISTA = 0 THEN CONCAT(ae.NC_MOTORISTA, ' (Não Cadast.)')
                       ELSE m.NM_MOTORISTA 
                   END as NOME_MOTORISTA, 
                   ae.ID_TIPOVEICULO, td.DE_TIPODEMANDA, ae.ID_TIPODEMANDA, 
                   tv.DE_TIPOVEICULO, ae.ID_VEICULO, ae.DT_INICIO, ae.DT_FIM,
                   ae.SETOR, ae.SOLICITANTE, ae.DESTINO, ae.NU_SEI, 
                   ae.DT_LANCAMENTO, ae.USUARIO, ae.OBS, ae.SOLICITADO, ae.HORARIO,
                   ae.TODOS_VEICULOS, ae.NC_MOTORISTA
            FROM AGENDA_DEMANDAS ae
            LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ae.ID_MOTORISTA
            LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
            LEFT JOIN TIPO_VEICULO tv ON tv.ID_TIPOVEICULO = ae.ID_TIPOVEICULO
            WHERE ae.ID_AD = %s
        """, (id_ad,))
        
        row = cursor.fetchone()
        
        if row:
            dt_lancamento = row[14].strftime('%Y-%m-%d %H:%M:%S') if row[14] else ''
            
            horario_formatado = ''
            if row[17]:
                try:
                    if isinstance(row[17], str):
                        horario_formatado = row[17][:5] if len(row[17]) >= 5 else ''
                    elif hasattr(row[17], 'total_seconds'):
                        total_seconds = int(row[17].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        if hours > 0 or minutes > 0:
                            horario_formatado = f"{hours:02d}:{minutes:02d}"
                    elif hasattr(row[17], 'strftime'):
                        horario_formatted = row[17].strftime('%H:%M')
                        if horario_formatted != '00:00':
                            horario_formatado = horario_formatted
                except:
                    horario_formatado = ''
            
            dados_demanda = {
                'id': row[0], 
                'id_motorista': row[1], 
                'nm_motorista': row[2],
                'id_tipoveiculo': row[3], 
                'de_tipodemanda': row[4], 
                'id_tipodemanda': row[5],
                'de_tipoveiculo': row[6], 
                'id_veiculo': row[7], 
                'dt_inicio': row[8].strftime('%Y-%m-%d'), 
                'dt_fim': row[9].strftime('%Y-%m-%d'),
                'setor': row[10] or '', 
                'solicitante': row[11] or '', 
                'destino': row[12] or '', 
                'nu_sei': row[13] or '', 
                'dt_lancamento': dt_lancamento,
                'usuario': row[15] or '',
                'obs': row[16] or '',
                'solicitado': row[17] or 'N',
                'horario': horario_formatado,
                'todos_veiculos': row[19] or 'N',  # ← Corrigir de row[18] para row[19]
                'nc_motorista': row[20] or ''      # ← Corrigir de row[19] para row[20]

            }
            
            # EMITIR WEBSOCKET
            emitir_alteracao_demanda('INSERT', id_ad, dados_demanda)
        
        cursor.close()
        
        return jsonify({'success': True, 'id': id_ad})
        
    except Exception as e:
        if cursor:
            mysql.connection.rollback()
        print(f"Erro ao criar demanda: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


# ============================================================
# BLOCO 5: ROTAS /api/v2/ - ATUALIZAR DEMANDA
# ============================================================

@app.route('/api/v2/agenda/demanda/<int:id_ad>', methods=['PUT'])
@login_required
def atualizar_demanda_v2(id_ad):
    """NOVA VERSÃO com emissão WebSocket"""
    cursor = None
    try:
        data = request.get_json()
        cursor = mysql.connection.cursor()

        usuario = session.get('usuario_login')
        
        # Buscar dados antigos
        cursor.execute("""
            SELECT ID_TIPODEMANDA, ID_MOTORISTA
            FROM AGENDA_DEMANDAS
            WHERE ID_AD = %s
        """, (id_ad,))
        
        dados_antigos = cursor.fetchone()
        id_tipodemanda_antigo = dados_antigos[0] if dados_antigos else None
        id_motorista_antigo = dados_antigos[1] if dados_antigos else None
        
        # Converter horário
        horario = data.get('horario')
        if horario and horario.strip():
            horario_value = horario + ':00'
        else:
            horario_value = None
        
        # Converter horário
        horario = data.get('horario')
        if horario and horario.strip():
            horario_value = horario + ':00'
        else:
            horario_value = None        
        
        id_tipodemanda_novo = data['id_tipodemanda']
        id_motorista_novo = data.get('id_motorista')
        id_veiculo_novo = data.get('id_veiculo')
        dt_inicio = data['dt_inicio']
        dt_fim = data['dt_fim']
        tem_horario = horario and horario.strip()
        
        # 1. Validar conflito de MOTORISTA (se mudou o motorista)
        if id_motorista_novo and int(id_motorista_novo) > 0:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM AGENDA_DEMANDAS
                WHERE ID_MOTORISTA = %s
                AND DT_INICIO <= %s
                AND DT_FIM >= %s
                AND ID_AD != %s
            """, (id_motorista_novo, dt_fim, dt_inicio, id_ad))
            
            if cursor.fetchone()[0] > 0:
                cursor.close()
                return jsonify({
                    'success': False,
                    'error': 'Este motorista já possui demanda(s) neste período.'
                }), 409

        # 2. Validar conflito de VEÍCULO (se mudou o veículo e não tem horário)
        if id_veiculo_novo and not tem_horario:
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM AGENDA_DEMANDAS
                WHERE ID_VEICULO = %s
                AND DT_INICIO <= %s
                AND DT_FIM >= %s
                AND (HORARIO IS NULL OR HORARIO = '00:00:00')
                AND ID_AD != %s
            """, (id_veiculo_novo, dt_fim, dt_inicio, id_ad))
            
            if cursor.fetchone()[0] > 0:
                cursor.close()
                return jsonify({
                    'success': False,
                    'error': 'Este veículo já possui demanda(s) SEM horário neste período.'
                }), 409

        # ATUALIZAR DEMANDA
        cursor.execute("""
            UPDATE AGENDA_DEMANDAS 
            SET ID_MOTORISTA = %s, ID_TIPOVEICULO = %s, ID_VEICULO = %s,
                ID_TIPODEMANDA = %s, DT_INICIO = %s, DT_FIM = %s,
                SETOR = %s, SOLICITANTE = %s, DESTINO = %s, NU_SEI = %s,
                OBS = %s, SOLICITADO = %s, HORARIO = %s, TODOS_VEICULOS = %s, 
                NC_MOTORISTA = %s, USUARIO = %s
            WHERE ID_AD = %s
        """, (
            id_motorista_novo, 
            data.get('id_tipoveiculo'), 
            data.get('id_veiculo'),
            id_tipodemanda_novo, 
            dt_inicio, 
            dt_fim,
            data.get('setor'), 
            data.get('solicitante'), 
            data.get('destino'), 
            data.get('nu_sei'),
            data.get('obs'),
            data.get('solicitado', 'N'),
            horario_value,
            data.get('todos_veiculos', 'N'),
            data.get('nc_motorista', ''),
            usuario, 
            id_ad
        ))

        # Gerenciar diárias terceirizados
        cursor.execute("""
            SELECT IDITEM FROM DIARIAS_TERCEIRIZADOS WHERE ID_AD = %s
        """, (id_ad,))
        
        diaria_terceirizado = cursor.fetchone()
        
        if diaria_terceirizado:
            precisa_excluir = False
            
            if id_tipodemanda_novo != 2:
                precisa_excluir = True
            
            if id_motorista_novo and int(id_motorista_novo) > 0:
                cursor.execute("""
                    SELECT m.ID_MOTORISTA
                    FROM CAD_MOTORISTA m
                    INNER JOIN CAD_FORNECEDOR f ON f.ID_FORNECEDOR = m.ID_FORNECEDOR
                    WHERE m.ID_MOTORISTA = %s
                      AND m.TIPO_CADASTRO = 'Terceirizado'
                      AND m.ATIVO = 'S'
                      AND f.VL_DIARIA IS NOT NULL
                      AND f.VL_DIARIA > 0
                """, (id_motorista_novo,))
                
                if not cursor.fetchone():
                    precisa_excluir = True
            else:
                precisa_excluir = True
            
            if precisa_excluir:
                cursor.execute("""
                    DELETE FROM DIARIAS_TERCEIRIZADOS WHERE ID_AD = %s
                """, (id_ad,))
        
        # Gerenciar diárias motorista atendimento
        mudou_tipo = id_tipodemanda_antigo != id_tipodemanda_novo
        mudou_motorista = id_motorista_antigo != id_motorista_novo
        
        if mudou_tipo or mudou_motorista:
            cursor.execute("""
                DELETE FROM DIARIAS_MOTORISTAS WHERE ID_AD = %s
            """, (id_ad,))
        
        gerenciar_diaria_motorista_atendimento(
            id_ad=id_ad,
            id_tipodemanda=id_tipodemanda_novo,
            id_motorista=id_motorista_novo,
            dt_inicio=dt_inicio,
            dt_fim=dt_fim,
            operacao='UPDATE'
        )
        
        mysql.connection.commit()
        
        # BUSCAR DADOS ATUALIZADOS PARA EMITIR
        cursor.execute("""
            SELECT ae.ID_AD, ae.ID_MOTORISTA, 
                   CASE 
                       WHEN ae.ID_MOTORISTA = 0 THEN CONCAT(ae.NC_MOTORISTA, ' (Não Cadast.)')
                       ELSE m.NM_MOTORISTA 
                   END as NOME_MOTORISTA, 
                   ae.ID_TIPOVEICULO, td.DE_TIPODEMANDA, ae.ID_TIPODEMANDA, 
                   tv.DE_TIPOVEICULO, ae.ID_VEICULO, ae.DT_INICIO, ae.DT_FIM,
                   ae.SETOR, ae.SOLICITANTE, ae.DESTINO, ae.NU_SEI, 
                   ae.DT_LANCAMENTO, ae.USUARIO, ae.OBS, ae.SOLICITADO, ae.HORARIO,
                   ae.TODOS_VEICULOS, ae.NC_MOTORISTA
            FROM AGENDA_DEMANDAS ae
            LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ae.ID_MOTORISTA
            LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
            LEFT JOIN TIPO_VEICULO tv ON tv.ID_TIPOVEICULO = ae.ID_TIPOVEICULO
            WHERE ae.ID_AD = %s
        """, (id_ad,))
        
        row = cursor.fetchone()
        
        if row:
            dt_lancamento = row[14].strftime('%Y-%m-%d %H:%M:%S') if row[14] else ''
            
            horario_formatado = ''
            if row[17]:
                try:
                    if isinstance(row[17], str):
                        horario_formatado = row[17][:5] if len(row[17]) >= 5 else ''
                    elif hasattr(row[17], 'total_seconds'):
                        total_seconds = int(row[17].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        if hours > 0 or minutes > 0:
                            horario_formatado = f"{hours:02d}:{minutes:02d}"
                    elif hasattr(row[17], 'strftime'):
                        horario_formatted = row[17].strftime('%H:%M')
                        if horario_formatted != '00:00':
                            horario_formatado = horario_formatted
                except:
                    horario_formatado = ''
            
            dados_demanda = {
                'id': row[0], 
                'id_motorista': row[1], 
                'nm_motorista': row[2],
                'id_tipoveiculo': row[3], 
                'de_tipodemanda': row[4], 
                'id_tipodemanda': row[5],
                'de_tipoveiculo': row[6], 
                'id_veiculo': row[7], 
                'dt_inicio': row[8].strftime('%Y-%m-%d'), 
                'dt_fim': row[9].strftime('%Y-%m-%d'),
                'setor': row[10] or '', 
                'solicitante': row[11] or '', 
                'destino': row[12] or '', 
                'nu_sei': row[13] or '', 
                'dt_lancamento': dt_lancamento,
                'usuario': row[15] or '',
                'obs': row[16] or '',
                'solicitado': row[17] or 'N',
                'horario': horario_formatado,
                'todos_veiculos': row[19] or 'N',  # ← Corrigir de row[18] para row[19]
                'nc_motorista': row[20] or ''      # ← Corrigir de row[19] para row[20]

            }
            
            # EMITIR WEBSOCKET
            emitir_alteracao_demanda('UPDATE', id_ad, dados_demanda)
        
        cursor.close()
        
        return jsonify({'success': True})
    
    except Exception as e:
        if cursor:
            mysql.connection.rollback()
        print(f"Erro ao atualizar demanda: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


# ============================================================
# BLOCO 6: ROTAS /api/v2/ - DELETAR DEMANDA
# ============================================================

@app.route('/api/v2/agenda/demanda/<int:id_ad>', methods=['DELETE'])
@login_required
def excluir_demanda_v2(id_ad):
    """NOVA VERSÃO com emissão WebSocket"""
    cursor = None
    try:
        cursor = mysql.connection.cursor()
        
        # Log de diárias
        cursor.execute("SELECT COUNT(*) FROM DIARIAS_MOTORISTAS WHERE ID_AD = %s", (id_ad,))
        tem_diaria_motorista = cursor.fetchone()[0] > 0
        
        cursor.execute("SELECT COUNT(*) FROM DIARIAS_TERCEIRIZADOS WHERE ID_AD = %s", (id_ad,))
        tem_diaria_terceirizado = cursor.fetchone()[0] > 0
        
        if tem_diaria_motorista:
            print(f"Excluindo demanda {id_ad} com diária de motorista atendimento")
        if tem_diaria_terceirizado:
            print(f"Excluindo demanda {id_ad} com diária de terceirizado")
        
        # Deleta dependências
        cursor.execute("DELETE FROM EMAIL_OUTRAS_LOCACOES WHERE ID_AD = %s", (id_ad,))
        cursor.execute("DELETE FROM CONTROLE_LOCACAO_ITENS WHERE ID_AD = %s", (id_ad,))
        cursor.execute("DELETE FROM AGENDA_DEMANDAS WHERE ID_AD = %s", (id_ad,))
        
        mysql.connection.commit()
        cursor.close()
        
        # EMITIR WEBSOCKET
        emitir_alteracao_demanda('DELETE', id_ad)
        
        return jsonify({'success': True})

    except Exception as e:
        if cursor:
            mysql.connection.rollback()
        print(f"Erro ao excluir demanda: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


# ============================================================
# BLOCO 7: ROTAS /api/v2/ - ENVIAR EMAIL
# ============================================================

@app.route('/api/v2/enviar_email_fornecedor', methods=['POST'])
@login_required
def enviar_email_fornecedor_v2():
    """NOVA VERSÃO com emissão WebSocket"""
    cursor = None
    try:
        email_destinatario = request.form.get('email_destinatario')
        assunto = request.form.get('assunto')
        corpo_html = request.form.get('corpo_html')
        id_demanda = request.form.get('id_demanda')
        id_item_fornecedor = request.form.get('id_item_fornecedor')
        tipo_email = request.form.get('tipo_email', 'locacao')
        
        if not all([email_destinatario, assunto, corpo_html, id_demanda]):
            return jsonify({'erro': 'Dados incompletos'}), 400
        
        # Processar anexos
        anexos = []
        if 'anexos' in request.files:
            files = request.files.getlist('anexos')
            for file in files:
                if file and file.filename:
                    anexos.append({
                        'nome': file.filename,
                        'conteudo': file.read(),
                        'tipo': file.content_type or 'application/octet-stream'
                    })
        
        nome_usuario = session.get('usuario_nome', 'Administrador')
        
        # Criar versão texto
        from html.parser import HTMLParser
        
        class HTMLToText(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
            def handle_data(self, data):
                self.text.append(data)
            def get_text(self):
                return ''.join(self.text)
        
        parser = HTMLToText()
        parser.feed(corpo_html)
        corpo_texto = parser.get_text()
        
        # Enviar email
        msg = Message(
            subject=assunto,
            recipients=[email_destinatario],
            html=corpo_html,
            body=corpo_texto,
            sender=("TJRO-SEGEOP", "segeop@tjro.jus.br")
        )
        
        for anexo in anexos:
            msg.attach(anexo['nome'], anexo['tipo'], anexo['conteudo'])
        
        mail.send(msg)
        
        # Registrar no banco
        cursor = mysql.connection.cursor()
        
        from pytz import timezone
        tz_manaus = timezone('America/Manaus')
        data_hora_atual = datetime.now(tz_manaus).strftime("%d/%m/%Y %H:%M:%S")
        
        if tipo_email == 'diarias':
            # EMAIL DE DIÁRIAS
            if not id_item_fornecedor or id_item_fornecedor == '0':
                cursor.execute("""
                    SELECT IDITEM FROM DIARIAS_TERCEIRIZADOS 
                    WHERE ID_AD = %s
                """, (id_demanda,))
                
                resultado_diaria = cursor.fetchone()
                
                if not resultado_diaria:
                    return jsonify({'erro': 'Registro de diária não encontrado'}), 400
                
                iditem_diaria = resultado_diaria[0]
            else:
                iditem_diaria = int(id_item_fornecedor)
            
            # Inserir em EMAIL_DIARIAS
            cursor.execute("""
                INSERT INTO EMAIL_DIARIAS 
                (IDITEM, ID_AD, DESTINATARIO, ASSUNTO, TEXTO, DATA_HORA) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (iditem_diaria, id_demanda, email_destinatario, assunto, corpo_texto, data_hora_atual))
            
            id_email = cursor.lastrowid
            
            # Atualizar FL_EMAIL
            cursor.execute("""
                UPDATE DIARIAS_TERCEIRIZADOS 
                SET FL_EMAIL = 'S' 
                WHERE IDITEM = %s
            """, (iditem_diaria,))
            
            mysql.connection.commit()
            
            # EMITIR WEBSOCKET
            emitir_alteracao_diaria_terceirizado('UPDATE', iditem_diaria, id_demanda, 'S')
        
        else:
            # EMAIL DE LOCAÇÃO
            cursor.execute("""
                INSERT INTO EMAIL_OUTRAS_LOCACOES 
                (ID_AD, ID_ITEM, DESTINATARIO, ASSUNTO, TEXTO, DATA_HORA) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (id_demanda, id_item_fornecedor or 0, email_destinatario, assunto, corpo_texto, data_hora_atual))
            
            id_email = cursor.lastrowid
            
            # Atualizar SOLICITADO
            cursor.execute("""
                UPDATE AGENDA_DEMANDAS 
                SET SOLICITADO = 'S' 
                WHERE ID_AD = %s
            """, (id_demanda,))
            
            if id_item_fornecedor:
                cursor.execute("""
                    UPDATE CONTROLE_LOCACAO_ITENS 
                    SET FL_EMAIL = 'S' 
                    WHERE ID_ITEM = %s
                """, (id_item_fornecedor,))
            
            mysql.connection.commit()
            
            # BUSCAR DADOS ATUALIZADOS E EMITIR
            cursor.execute("""
                SELECT ae.ID_AD, ae.ID_MOTORISTA, 
                       CASE 
                           WHEN ae.ID_MOTORISTA = 0 THEN CONCAT(ae.NC_MOTORISTA, ' (Não Cadast.)')
                           ELSE m.NM_MOTORISTA 
                       END as NOME_MOTORISTA, 
                       ae.ID_TIPOVEICULO, td.DE_TIPODEMANDA, ae.ID_TIPODEMANDA, 
                       tv.DE_TIPOVEICULO, ae.ID_VEICULO, ae.DT_INICIO, ae.DT_FIM,
                       ae.SETOR, ae.SOLICITANTE, ae.DESTINO, ae.NU_SEI, 
                       ae.DT_LANCAMENTO, ae.USUARIO, ae.OBS, ae.SOLICITADO, ae.HORARIO,
                       ae.TODOS_VEICULOS, ae.NC_MOTORISTA
                FROM AGENDA_DEMANDAS ae
                LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ae.ID_MOTORISTA
                LEFT JOIN TIPO_DEMANDA td ON td.ID_TIPODEMANDA = ae.ID_TIPODEMANDA
                LEFT JOIN TIPO_VEICULO tv ON tv.ID_TIPOVEICULO = ae.ID_TIPOVEICULO
                WHERE ae.ID_AD = %s
            """, (id_demanda,))
            
            row = cursor.fetchone()
            
            if row:
                dt_lancamento = row[14].strftime('%Y-%m-%d %H:%M:%S') if row[14] else ''
                
                horario_formatado = ''
                if row[17]:
                    try:
                        if isinstance(row[17], str):
                            horario_formatado = row[17][:5]
                        elif hasattr(row[17], 'total_seconds'):
                            total_seconds = int(row[17].total_seconds())
                            hours = total_seconds // 3600
                            minutes = (total_seconds % 3600) // 60
                            if hours > 0 or minutes > 0:
                                horario_formatado = f"{hours:02d}:{minutes:02d}"
                        elif hasattr(row[17], 'strftime'):
                            horario_formatted = row[17].strftime('%H:%M')
                            if horario_formatted != '00:00':
                                horario_formatado = horario_formatted
                    except:
                        horario_formatado = ''
                
                dados_demanda = {
                    'id': row[0], 
                    'id_motorista': row[1], 
                    'nm_motorista': row[2],
                    'id_tipoveiculo': row[3], 
                    'de_tipodemanda': row[4], 
                    'id_tipodemanda': row[5],
                    'de_tipoveiculo': row[6], 
                    'id_veiculo': row[7], 
                    'dt_inicio': row[8].strftime('%Y-%m-%d'), 
                    'dt_fim': row[9].strftime('%Y-%m-%d'),
                    'setor': row[10] or '', 
                    'solicitante': row[11] or '', 
                    'destino': row[12] or '', 
                    'nu_sei': row[13] or '', 
                    'dt_lancamento': dt_lancamento,
                    'usuario': row[15] or '',
                    'obs': row[16] or '',
                    'solicitado': row[17] or 'N',
                    'horario': horario_formatado,
                    'todos_veiculos': row[19] or 'N',  # ← row[19] não row[18]
                    'nc_motorista': row[20] or ''      # ← row[20] não row[19]
                }
                
                emitir_alteracao_demanda('UPDATE', id_demanda, dados_demanda)
        
        cursor.close()
        
        return jsonify({
            'success': True,
            'id_email': id_email,
            'mensagem': 'Email enviado com sucesso!'
        })
        
    except Exception as e:
        print(f"❌ Erro ao enviar email: {str(e)}")
        import traceback
        traceback.print_exc()
        if cursor:
            mysql.connection.rollback()
        return jsonify({'erro': str(e)}), 500
    finally:
        if cursor:
            cursor.close()


"""
============================================================
ROTAS PARA GESTÃO DE CONTRATOS TERCEIRIZADOS
============================================================
Adicionar estas rotas ao arquivo app.py
"""

# ============================================================
# ROTA PRINCIPAL - PÁGINA DE GESTÃO DE TERCEIRIZADOS
# ============================================================
@app.route('/gestao-terceirizados')
@login_required
def gestao_terceirizados():
    return render_template('gestao_terceirizados.html')

# ============================================================
# ROTA - RELATÓRIO DE FISCALIZAÇÃO (IMPRESSÃO)
# ============================================================
@app.route('/relatorio-fiscalizacao-impressao')
@login_required
def relatorio_fiscalizacao_impressao():
    """Página separada para impressão do relatório de fiscalização"""
    return render_template('rel_fiscalizacao.html')
		
# ============================================================
# API - LISTAR CONTRATOS
# ============================================================
@app.route('/api/gestao-terceirizados/contratos', methods=['GET'])
def api_listar_contratos_terceirizados():
    """Lista todos os contratos terceirizados"""
    # if 'loggedin' not in session:
    #     return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = """
            SELECT 
                gct.ID_CONTRATO,
                gce.EXERCICIO,
                gce.PROCESSO,
                gct.CONTRATO,
                cf.NM_FORNECEDOR
            FROM GESTAO_CONTRATOS_TERCEIRIZADOS gct
            LEFT JOIN CAD_FORNECEDOR cf ON cf.ID_FORNECEDOR = gct.ID_FORNECEDOR
            JOIN GESTAO_CONTRATOS_EXERCICIOS gce ON gce.ID_CONTRATO = gct.ID_CONTRATO
            ORDER BY gce.EXERCICIO DESC, cf.NM_FORNECEDOR
        """
        
        cursor.execute(query)
        contratos = cursor.fetchall()
        cursor.close()
        
        return jsonify({
            'success': True,
            'data': contratos
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - OBTER DETALHES DE UM CONTRATO
# ============================================================
@app.route('/api/gestao-terceirizados/contratos/<int:id_contrato>', methods=['GET'])
def api_obter_contrato_terceirizado(id_contrato):
    """Obtém os detalhes de um contrato específico"""
    # if 'loggedin' not in session:
    #     return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = """
            SELECT 
                gct.ID_CONTRATO,
                gct.ID_FORNECEDOR,
                gce.EXERCICIO,
                gce.PROCESSO,
                gct.ATA_PREGAO,
                gct.CONTRATO,
                gct.SETOR_GESTOR,
                gct.NOME_GESTOR,
                gct.CIDADE,
                gct.VL_CONTRATO,
                gct.ELEMENTO_DESPESA,
                gct.UO,
                gct.CAT_CONTRATO,
                gct.TIPO_CONTRATO,
                cf.NM_FORNECEDOR
            FROM GESTAO_CONTRATOS_TERCEIRIZADOS gct
            LEFT JOIN CAD_FORNECEDOR cf ON cf.ID_FORNECEDOR = gct.ID_FORNECEDOR
			JOIN GESTAO_CONTRATOS_EXERCICIOS gce ON gce.ID_CONTRATO = gct.ID_CONTRATO
            WHERE gct.ID_CONTRATO = %s
        """
        
        cursor.execute(query, (id_contrato,))
        contrato = cursor.fetchone()
        cursor.close()
        
        if contrato:
            return jsonify({
                'success': True,
                'data': contrato
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Contrato não encontrado'
            }), 404
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - LISTAR VÍNCULOS (MOTORISTAS E POSTOS)
# ============================================================
@app.route('/api/gestao-terceirizados/vinculos/<int:id_contrato>', methods=['GET'])
def api_listar_vinculos_terceirizados(id_contrato):
    """Lista os vínculos de motoristas e postos de trabalho de um contrato"""
    # if 'loggedin' not in session:
    #     return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = """
            SELECT 
                ptv.ID_VINCULO, 
                ptv.ID_POSTO, 
                pt.DE_POSTO,
                ptv.ID_MOTORISTA,
                m.NM_MOTORISTA,
                cmp.DT_INICIO,
                cmp.DT_FIM,
                ptvl.VL_MENSAL,
                ptvl.VL_SALARIO
            FROM POSTO_TRABALHO pt
            JOIN POSTO_TRABALHO_VINCULO ptv ON ptv.ID_POSTO = pt.ID_POSTO
            JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ptv.ID_MOTORISTA
            JOIN CAD_MOTORISTA_PERIODOS cmp ON cmp.ID_MOTORISTA = m.ID_MOTORISTA
                AND cmp.DT_FIM IS NULL
            JOIN POSTO_TRABALHO_VALORES ptvl ON ptvl.ID_POSTO = pt.ID_POSTO 
                AND ptvl.DT_FIM IS NULL
            WHERE cmp.DT_INICIO <= CURDATE()
                AND pt.ID_CONTRATO = %s
            ORDER BY m.NM_MOTORISTA
        """
        
        cursor.execute(query, (id_contrato,))
        vinculos = cursor.fetchall()
        cursor.close()
        
        return jsonify({
            'success': True,
            'data': vinculos
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - LISTAR IMPERFEIÇÕES
# ============================================================
@app.route('/api/gestao-terceirizados/imperfeicoes', methods=['GET'])
def api_listar_imperfeicoes():
    """Lista todas as imperfeições cadastradas"""
    # if 'loggedin' not in session:
    #     return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = """
            SELECT 
                ID_IMPERFEICAO,
                CONCAT(LPAD(ID_IMPERFEICAO, 2, '0'),' - ',DESCRICAO) AS DESCRICAO,
                TOLERANCIA,
                MULTIPLICADOR
            FROM LISTA_IMPERFEICOES
            ORDER BY ID_IMPERFEICAO
        """
        
        cursor.execute(query)
        imperfeicoes = cursor.fetchall()
        cursor.close()
        
        return jsonify({
            'success': True,
            'data': imperfeicoes
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - LISTAR OCORRÊNCIAS
# ============================================================
@app.route('/api/gestao-terceirizados/ocorrencias/<int:id_contrato>', methods=['GET'])
def api_listar_ocorrencias(id_contrato):
    """Lista as ocorrências de um contrato filtradas por mês/ano de competência"""
    try:
        mes = request.args.get('mes', '')
        ano = request.args.get('ano', '')
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = """
            SELECT 
                ot.ID_OCORRENCIA,
                ot.ID_CONTRATO,
                ot.ID_MOTORISTA,
                m.NM_MOTORISTA,
                ot.ID_IMPERFEICAO,
                ot.DATA_OCORRENCIA,
                ot.MES,
                ot.ANO,
                ot.ESPECIFICACAO,
				CONCAT(LPAD(li.ID_IMPERFEICAO, 2, '0'),' - ',li.DESCRICAO) AS DESCRICAO,
                li.TOLERANCIA,
                li.MULTIPLICADOR
            FROM OCORRENCIAS_TERCEIRIZADOS ot
            JOIN LISTA_IMPERFEICOES li ON li.ID_IMPERFEICAO = ot.ID_IMPERFEICAO
            LEFT JOIN CAD_MOTORISTA m ON m.ID_MOTORISTA = ot.ID_MOTORISTA
            WHERE ot.ID_CONTRATO = %s
        """
        
        params = [id_contrato]
        
        # Filtrar por MES e ANO de competência
        if mes and ano:
            # Converter número do mês para nome do mês
            meses = {
                '01': 'Janeiro', '02': 'Fevereiro', '03': 'Março', '04': 'Abril',
                '05': 'Maio', '06': 'Junho', '07': 'Julho', '08': 'Agosto',
                '09': 'Setembro', '10': 'Outubro', '11': 'Novembro', '12': 'Dezembro'
            }
            nome_mes = meses.get(mes, '')
            if nome_mes:
                query += " AND ot.MES = %s AND ot.ANO = %s"
                params.extend([nome_mes, int(ano)])
        
        query += " ORDER BY ot.ANO DESC, FIELD(ot.MES, 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro') DESC, ot.DATA_OCORRENCIA DESC"
        
        cursor.execute(query, params)
        ocorrencias = cursor.fetchall()
        cursor.close()
        
        # Converter datas para string formato ISO
        for ocorrencia in ocorrencias:
            if ocorrencia.get('DATA_OCORRENCIA'):
                ocorrencia['DATA_OCORRENCIA'] = ocorrencia['DATA_OCORRENCIA'].strftime('%Y-%m-%d')
        
        return jsonify({
            'success': True,
            'data': ocorrencias
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - OBTER DETALHES DE UMA OCORRÊNCIA
# ============================================================
@app.route('/api/gestao-terceirizados/ocorrencias/detalhe/<int:id_ocorrencia>', methods=['GET'])
def api_obter_ocorrencia(id_ocorrencia):
    """Obtém os detalhes de uma ocorrência específica"""
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = """
            SELECT 
                ID_OCORRENCIA,
                ID_CONTRATO,
                ID_MOTORISTA,
                ID_IMPERFEICAO,
                DATA_OCORRENCIA,
                MES,
                ANO,
                ESPECIFICACAO
            FROM OCORRENCIAS_TERCEIRIZADOS
            WHERE ID_OCORRENCIA = %s
        """
        
        cursor.execute(query, (id_ocorrencia,))
        ocorrencia = cursor.fetchone()
        cursor.close()
        
        if ocorrencia:
            # Converter data para string formato ISO
            if ocorrencia.get('DATA_OCORRENCIA'):
                ocorrencia['DATA_OCORRENCIA'] = ocorrencia['DATA_OCORRENCIA'].strftime('%Y-%m-%d')
            
            return jsonify({
                'success': True,
                'data': ocorrencia
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Ocorrência não encontrada'
            }), 404
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - INSERIR OCORRÊNCIA
# ============================================================
@app.route('/api/gestao-terceirizados/ocorrencias', methods=['POST'])
def api_inserir_ocorrencia():
    """Insere uma nova ocorrência"""
    try:
        data = request.get_json()
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Obter o próximo ID
        cursor.execute("SELECT COALESCE(MAX(ID_OCORRENCIA), 0) + 1 as NEXT_ID FROM OCORRENCIAS_TERCEIRIZADOS")
        next_id = cursor.fetchone()['NEXT_ID']
        
        query = """
            INSERT INTO OCORRENCIAS_TERCEIRIZADOS 
            (ID_OCORRENCIA, ID_CONTRATO, ID_MOTORISTA, ID_IMPERFEICAO, DATA_OCORRENCIA, MES, ANO, ESPECIFICACAO)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            next_id,
            data.get('id_contrato'),
            data.get('id_motorista'),
            data.get('id_imperfeicao'),
            data.get('data_ocorrencia'),
            data.get('mes_competencia'),
            data.get('ano_competencia'),
            data.get('especificacao', '')
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'success': True,
            'message': 'Ocorrência cadastrada com sucesso',
            'id_ocorrencia': next_id
        })
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - ATUALIZAR OCORRÊNCIA
# ============================================================
@app.route('/api/gestao-terceirizados/ocorrencias/<int:id_ocorrencia>', methods=['PUT'])
def api_atualizar_ocorrencia(id_ocorrencia):
    """Atualiza uma ocorrência existente"""
    try:
        data = request.get_json()
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = """
            UPDATE OCORRENCIAS_TERCEIRIZADOS 
            SET ID_MOTORISTA = %s,
                ID_IMPERFEICAO = %s,
                DATA_OCORRENCIA = %s,
                MES = %s,
                ANO = %s,
                ESPECIFICACAO = %s
            WHERE ID_OCORRENCIA = %s
        """
        
        cursor.execute(query, (
            data.get('id_motorista'),
            data.get('id_imperfeicao'),
            data.get('data_ocorrencia'),
            data.get('mes_competencia'),
            data.get('ano_competencia'),
            data.get('especificacao', ''),
            id_ocorrencia
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'success': True,
            'message': 'Ocorrência atualizada com sucesso'
        })
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - EXCLUIR OCORRÊNCIA
# ============================================================
@app.route('/api/gestao-terceirizados/ocorrencias/<int:id_ocorrencia>', methods=['DELETE'])
def api_excluir_ocorrencia(id_ocorrencia):
    """Exclui uma ocorrência"""
    # if 'loggedin' not in session:
    #     return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        query = "DELETE FROM OCORRENCIAS_TERCEIRIZADOS WHERE ID_OCORRENCIA = %s"
        cursor.execute(query, (id_ocorrencia,))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({
            'success': True,
            'message': 'Ocorrência excluída com sucesso'
        })
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================
# API - RELATÓRIO DE FISCALIZAÇÃO
# ============================================================
# Adicionar esta rota ANTES do "if __name__ == '__main__':" no app.py

@app.route('/api/gestao-terceirizados/relatorio-fiscalizacao', methods=['POST'])
def api_relatorio_fiscalizacao():
    """Gera o relatório de fiscalização mensal"""
    # if 'loggedin' not in session:
    #     return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        data = request.get_json()
        id_contrato = data.get('id_contrato')
        mes = data.get('mes')
        ano = data.get('ano')
        
        if not all([id_contrato, mes, ano]):
            return jsonify({
                'success': False,
                'error': 'Parâmetros obrigatórios: id_contrato, mes, ano'
            }), 400
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # ===================================
        # 1. BUSCAR DADOS DO CONTRATO
        # ===================================
        query_contrato = """
            SELECT 
                c.CONTRATO,
                g.PROCESSO,
                c.NOME_GESTOR,
                c.SETOR_GESTOR,
                f.NM_FORNECEDOR
            FROM GESTAO_CONTRATOS_TERCEIRIZADOS c
            LEFT JOIN CAD_FORNECEDOR f ON c.ID_FORNECEDOR = f.ID_FORNECEDOR
			JOIN GESTAO_CONTRATOS_EXERCICIOS g ON g.ID_CONTRATO = c.ID_CONTRATO
            WHERE c.ID_CONTRATO = %s
        """
        cursor.execute(query_contrato, (id_contrato,))
        contrato = cursor.fetchone()
        
        if not contrato:
            return jsonify({'success': False, 'error': 'Contrato não encontrado'}), 404
        
        # ===================================
        # 2. BUSCAR LISTA DE IMPERFEIÇÕES
        # ===================================
        query_imperfeicoes = """
            SELECT 
                ID_IMPERFEICAO,
                DESCRICAO,
                TOLERANCIA,
                MULTIPLICADOR
            FROM LISTA_IMPERFEICOES
            ORDER BY ID_IMPERFEICAO
        """
        cursor.execute(query_imperfeicoes)
        imperfeicoes = cursor.fetchall()
        
        # ===================================
        # 3. BUSCAR POSTOS DE TRABALHO
        # ===================================
        query_postos = """
            SELECT 
                ID_POSTO,
                DE_POSTO
            FROM POSTO_TRABALHO
            WHERE ID_CONTRATO = %s
            ORDER BY DE_POSTO
        """
        cursor.execute(query_postos, (id_contrato,))
        postos = cursor.fetchall()
        
        # ===================================
        # 4. CALCULAR PRIMEIRO E ÚLTIMO DIA DO MÊS
        # ===================================
        from calendar import monthrange
        ano_int = int(ano)
        meses = {
            'JANEIRO': 1, 'FEVEREIRO': 2, 'MARÇO': 3, 'ABRIL': 4,
            'MAIO': 5, 'JUNHO': 6, 'JULHO': 7, 'AGOSTO': 8,
            'SETEMBRO': 9, 'OUTUBRO': 10, 'NOVEMBRO': 11, 'DEZEMBRO': 12
        }
        mes_numero = meses.get(mes.upper())
        
        if not mes_numero:
            return jsonify({'success': False, 'error': 'Mês inválido'}), 400
        
        primeiro_dia = datetime(ano_int, mes_numero, 1).date()
        ultimo_dia = datetime(ano_int, mes_numero, monthrange(ano_int, mes_numero)[1]).date()
        
        # ===================================
        # 5. PROCESSAR CADA POSTO DE TRABALHO
        # ===================================
        resultado_postos = []
        
        for posto in postos:
            id_posto = posto['ID_POSTO']
            nome_posto = posto['DE_POSTO']
            
            # 5.1. Buscar ocorrências por imperfeição
            ocorrencias_por_imperfeicao = {}
            for imp in imperfeicoes:
                query_count = """
                    SELECT COUNT(*) as total
                    FROM OCORRENCIAS_TERCEIRIZADOS o
                    INNER JOIN POSTO_TRABALHO_VINCULO v ON o.ID_MOTORISTA = v.ID_MOTORISTA
                    WHERE v.ID_POSTO = %s
                    AND o.ID_IMPERFEICAO = %s
                    AND o.MES = %s
                    AND o.ANO = %s
                """
                cursor.execute(query_count, (id_posto, imp['ID_IMPERFEICAO'], mes, ano))
                result = cursor.fetchone()
                ocorrencias_por_imperfeicao[imp['ID_IMPERFEICAO']] = result['total']
            
            # 5.2. Calcular números corrigidos por imperfeição
            numeros_corrigidos = []
            for imp in imperfeicoes:
                total_ocorrencias = ocorrencias_por_imperfeicao[imp['ID_IMPERFEICAO']]
                tolerancia = imp['TOLERANCIA']
                multiplicador = imp['MULTIPLICADOR']
                
                if total_ocorrencias > tolerancia:
                    excesso = total_ocorrencias - tolerancia
                    numero_corrigido = excesso * multiplicador
                else:
                    numero_corrigido = 0
                
                numeros_corrigidos.append(numero_corrigido)
            
            # 5.3. Buscar quantidade de motoristas no posto
            query_motoristas = """
                SELECT DISTINCT v.ID_MOTORISTA
                FROM POSTO_TRABALHO_VINCULO v
                INNER JOIN CAD_MOTORISTA_PERIODOS p ON v.ID_MOTORISTA = p.ID_MOTORISTA
                WHERE v.ID_POSTO = %s
                AND p.DT_INICIO <= %s
                AND (p.DT_FIM IS NULL OR p.DT_FIM >= %s)
            """
            cursor.execute(query_motoristas, (id_posto, ultimo_dia, primeiro_dia))
            motoristas = cursor.fetchall()
            qtd_motoristas = len(motoristas)
            
            # 5.4. Separar motoristas que trabalharam mês completo vs parcial
            motoristas_completo = []
            motoristas_parcial = []
            
            for mot in motoristas:
                id_motorista = mot['ID_MOTORISTA']
                
                # ✅ CORREÇÃO: Buscar TODOS os períodos do motorista no mês
                query_periodos = """
                    SELECT DT_INICIO, DT_FIM
                    FROM CAD_MOTORISTA_PERIODOS
                    WHERE ID_MOTORISTA = %s
                    AND DT_INICIO <= %s
                    AND (DT_FIM IS NULL OR DT_FIM >= %s)
                    ORDER BY DT_INICIO
                """
                cursor.execute(query_periodos, (id_motorista, ultimo_dia, primeiro_dia))
                periodos = cursor.fetchall()
                
                if periodos:
                    # Verificar se tem período que cobre o mês completo
                    tem_mes_completo = False
                    for periodo in periodos:
                        dt_inicio = periodo['DT_INICIO']
                        dt_fim = periodo['DT_FIM']
                        
                        if dt_inicio <= primeiro_dia and (dt_fim is None or dt_fim >= ultimo_dia):
                            tem_mes_completo = True
                            break
                    
                    if tem_mes_completo:
                        motoristas_completo.append({
                            'id_motorista': id_motorista,
                            'dias_trabalhados': 30
                        })
                    else:
                        # ✅ CORREÇÃO: Somar dias de TODOS os períodos
                        total_dias = 0
                        periodos_info = []
                        
                        for periodo in periodos:
                            dt_inicio = periodo['DT_INICIO']
                            dt_fim = periodo['DT_FIM']
                            
                            # Ajustar para os limites do mês
                            inicio_calculo = max(dt_inicio, primeiro_dia)
                            fim_calculo = min(dt_fim if dt_fim else ultimo_dia, ultimo_dia)
                            
                            # Calcular dias deste período
                            dias_periodo = (fim_calculo - inicio_calculo).days + 1
                            total_dias += dias_periodo
                            
                            periodos_info.append({
                                'dt_inicio': dt_inicio,
                                'dt_fim': dt_fim,
                                'dias': dias_periodo
                            })
                        
                        # Buscar nome do motorista para observação
                        query_nome = "SELECT NM_MOTORISTA FROM CAD_MOTORISTA WHERE ID_MOTORISTA = %s"
                        cursor.execute(query_nome, (id_motorista,))
                        nome_result = cursor.fetchone()
                        nome_motorista = nome_result['NM_MOTORISTA'] if nome_result else 'Não identificado'
                        
                        motoristas_parcial.append({
                            'id_motorista': id_motorista,
                            'nome_motorista': nome_motorista,
                            'dias_trabalhados': total_dias,
                            'periodos': periodos_info
                        })
            
            # 5.5. Buscar valor mensal do posto
            query_valor = """
                SELECT VL_MENSAL
                FROM POSTO_TRABALHO_VALORES
                WHERE ID_POSTO = %s
                AND DT_INICIO <= %s
                AND (DT_FIM IS NULL OR DT_FIM >= %s)
                ORDER BY DT_INICIO DESC
                LIMIT 1
            """
            cursor.execute(query_valor, (id_posto, ultimo_dia, primeiro_dia))
            valor_result = cursor.fetchone()
            vl_mensal = float(valor_result['VL_MENSAL']) if valor_result else 0
            
            # 5.6. Adicionar ao resultado
            resultado_postos.append({
                'id_posto': id_posto,
                'nome_posto': nome_posto,
                'qtd_motoristas_total': qtd_motoristas,
                'qtd_motoristas_completo': len(motoristas_completo),
                'qtd_motoristas_parcial': len(motoristas_parcial),
                'motoristas_completo': motoristas_completo,
                'motoristas_parcial': motoristas_parcial,
                'ocorrencias': ocorrencias_por_imperfeicao,
                'numeros_corrigidos': numeros_corrigidos,
                'vl_mensal': vl_mensal
            })
        
        # ===================================
        # 6. CALCULAR FATOR DE ACEITAÇÃO TOTAL
        # ===================================
        somatorio_fator = sum([
            sum(posto['numeros_corrigidos']) 
            for posto in resultado_postos
        ])
        
        # ===================================
        # 7. DETERMINAR FAIXA E PERCENTUAIS
        # ===================================
        faixas = [
            {'nome': '-', 'min': 0, 'max': 0, 'percentual_receber': 100, 'percentual_glosa': 0},
            {'nome': 'A', 'min': 1, 'max': 100, 'percentual_receber': 95, 'percentual_glosa': 5},
            {'nome': 'B', 'min': 101, 'max': 200, 'percentual_receber': 90, 'percentual_glosa': 10},
            {'nome': 'C', 'min': 201, 'max': 300, 'percentual_receber': 85, 'percentual_glosa': 15},
            {'nome': 'D', 'min': 301, 'max': 400, 'percentual_receber': 80, 'percentual_glosa': 20},
            {'nome': 'E', 'min': 401, 'max': 500, 'percentual_receber': 75, 'percentual_glosa': 25},
            {'nome': 'F', 'min': 501, 'max': 600, 'percentual_receber': 70, 'percentual_glosa': 30},
        ]
        
        faixa_alcancada = None
        for faixa in faixas:
            if faixa['min'] <= somatorio_fator <= faixa['max']:
                faixa_alcancada = faixa
                break
        
        # Se ultrapassou 600, usar faixa F
        if not faixa_alcancada:
            faixa_alcancada = faixas[-1]
        
        percentual_receber = faixa_alcancada['percentual_receber']
        percentual_glosa = faixa_alcancada['percentual_glosa']
        
        # ===================================
        # 8. CALCULAR VALORES POR LOCALIDADE
        # ===================================
        localidades = []
        observacoes_parciais = []
        valor_referencia_total = 0
        valor_devido_total = 0
        
        for posto in resultado_postos:
            vl_mensal = posto['vl_mensal']
            
            # Motoristas mês completo
            if posto['qtd_motoristas_completo'] > 0:
                qtd = posto['qtd_motoristas_completo']
                valor_ref_mensal = vl_mensal
                valor_ref_total = valor_ref_mensal * qtd
                
                valor_dev_mensal = valor_ref_mensal * (percentual_receber / 100)
                valor_dev_total = valor_dev_mensal * qtd
                
                localidades.append({
                    'nome': posto['nome_posto'],
                    'tem_asterisco': False,
                    'qtd_posto': qtd,
                    'valor_ref_mensal': valor_ref_mensal,
                    'valor_ref_total': valor_ref_total,
                    'valor_dev_mensal': valor_dev_mensal,
                    'valor_dev_total': valor_dev_total
                })
                
                valor_referencia_total += valor_ref_total
                valor_devido_total += valor_dev_total
            
            # Motoristas mês parcial
            if posto['qtd_motoristas_parcial'] > 0:
                for mot_parcial in posto['motoristas_parcial']:
                    dias_trab = mot_parcial['dias_trabalhados']
                    
                    # Valor proporcional
                    valor_ref_mensal = vl_mensal
                    valor_ref_total = valor_ref_mensal  # Mantém valor total
                    
                    valor_dev_mensal = (vl_mensal / 30) * dias_trab
                    valor_dev_mensal = valor_dev_mensal * (percentual_receber / 100)
                    valor_dev_total = valor_dev_mensal
                    
                    localidades.append({
                        'nome': posto['nome_posto'],
                        'tem_asterisco': True,
                        'qtd_posto': 1,
                        'dias_trabalhados': dias_trab,
                        'valor_ref_mensal': valor_ref_mensal,
                        'valor_ref_total': valor_ref_total,
                        'valor_dev_mensal': valor_dev_mensal,
                        'valor_dev_total': valor_dev_total
                    })
                    
                    # ✅ NOVA FUNCIONALIDADE: Adicionar à observação
                    observacoes_parciais.append({
                        'posto': posto['nome_posto'],
                        'nome': mot_parcial['nome_motorista'],
                        'dias': dias_trab,
                        'valor': valor_dev_total
                    })
                    
                    valor_referencia_total += valor_ref_total
                    valor_devido_total += valor_dev_total
        
        # ===================================
        # 9. CALCULAR VALOR DA GLOSA
        # ===================================
        # ✅ CORREÇÃO: Glosa só existe se percentual_glosa > 0
        if percentual_glosa > 0:
            valor_glosa = valor_referencia_total - valor_devido_total
        else:
            valor_glosa = 0.0
        
        # ===================================
        # 10. MONTAR RESPOSTA FINAL
        # ===================================
        cursor.close()
        
        return jsonify({
            'success': True,
            'data': {
                'cabecalho': {
                    'contrato': contrato['CONTRATO'],
                    'protocolo': contrato['PROCESSO'],
                    'contratada': contrato['NM_FORNECEDOR'],
                    'objeto': 'Serviço de apoio operacional - MOTORISTA',
                    'mes_ano': f"{mes}/{ano}",
                    'gestor': contrato['NOME_GESTOR'],
                    'unidade': contrato['SETOR_GESTOR']
                },
                'imperfeicoes': [
                    {
                        'id': imp['ID_IMPERFEICAO'],
                        'descricao': imp['DESCRICAO'],
                        'tolerancia': imp['TOLERANCIA'],
                        'multiplicador': imp['MULTIPLICADOR']
                    }
                    for imp in imperfeicoes
                ],
                'postos': resultado_postos,
                'somatorio_fator': somatorio_fator,
                'faixa_alcancada': faixa_alcancada['nome'],
                'faixas': faixas,
                'percentual_receber': percentual_receber,
                'percentual_glosa': percentual_glosa,
                'houve_glosa': percentual_glosa > 0,
                'localidades': localidades,
                'observacoes_parciais': observacoes_parciais,  # ✅ NOVO
                'totais': {
                    'valor_referencia_total': valor_referencia_total,
                    'valor_devido_total': valor_devido_total,
                    'valor_glosa': valor_glosa
                }
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/gestao-terceirizados/relatorio-fiscalizacao-pdf', methods=['GET'])
def api_relatorio_fiscalizacao_pdf():
    """Gera PDF do relatório usando xhtml2pdf (mais estável)"""
    try:
        id_contrato = request.args.get('id_contrato')
        mes = request.args.get('mes')
        ano = request.args.get('ano')
        
        if not all([id_contrato, mes, ano]):
            return "Parâmetros obrigatórios: id_contrato, mes, ano", 400
        
        # Obter dados do relatório
        with app.test_client() as client:
            response = client.post(
                '/api/gestao-terceirizados/relatorio-fiscalizacao',
                json={
                    'id_contrato': int(id_contrato),
                    'mes': mes,
                    'ano': ano
                },
                content_type='application/json'
            )
            
            if response.status_code != 200:
                return "Erro ao gerar relatório", 500
            
            result = response.get_json()
            if not result.get('success'):
                return f"Erro: {result.get('error', 'Desconhecido')}", 500
                
            data = result['data']
        
        # Gerar HTML simplificado
        html_content = gerar_html_relatorio_pdf_simples(data)
        
        # Gerar PDF com xhtml2pdf
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(
            src=html_content,
            dest=pdf_buffer,
            encoding='utf-8'
        )
        
        if pisa_status.err:
            return "Erro ao criar PDF", 500
        
        pdf_buffer.seek(0)
        
        # Retornar PDF
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=relatorio_{mes}_{ano}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Erro ao gerar PDF: {str(e)}", 500

@app.route('/api/gestao-terceirizados/relatorio-fiscalizacao-html', methods=['GET'])
def api_relatorio_fiscalizacao_html():
    """Retorna o relatório como HTML para abrir em nova aba"""
    try:
        id_contrato = request.args.get('id_contrato')
        mes = request.args.get('mes')
        ano = request.args.get('ano')
        
        if not all([id_contrato, mes, ano]):
            return "Parâmetros obrigatórios: id_contrato, mes, ano", 400
        
        # Obter dados do relatório
        with app.test_client() as client:
            response = client.post(
                '/api/gestao-terceirizados/relatorio-fiscalizacao',
                json={
                    'id_contrato': int(id_contrato),
                    'mes': mes,
                    'ano': ano
                },
                content_type='application/json'
            )
            
            if response.status_code != 200:
                return "Erro ao gerar relatório", 500
            
            result = response.get_json()
            if not result.get('success'):
                return f"Erro: {result.get('error', 'Desconhecido')}", 500
                
            data = result['data']
        
        # Gerar HTML para impressão
        html_content = gerar_html_relatorio_impressao(data)
        
        # Retornar HTML puro
        return html_content
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Erro ao gerar relatório: {str(e)}", 500

def gerar_html_relatorio_impressao(data):
    """Gera HTML formatado para impressão (A4 retrato)"""
    
    def formatar_moeda(valor):
        if valor is None:
            valor = 0.0
        return f"R$ {float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    def safe_float(val, default=0.0):
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    
    # Preparar dados
    imperfeicoes = data.get('imperfeicoes', [])[:10]
    postos = data.get('postos', [])
    
    # Calcular totais
    totais = [0] * 10
    for posto in postos:
        for i in range(1, 11):
            totais[i-1] += posto.get('ocorrencias', {}).get(i, 0) or 0
    
    tolerancias = [imp.get('tolerancia', 0) for imp in imperfeicoes]
    excessos = [max(0, totais[i] - (tolerancias[i] or 0)) for i in range(len(tolerancias))]
    multiplicadores = [imp.get('multiplicador', 0) for imp in imperfeicoes]
    corrigidos = [excessos[i] * (multiplicadores[i] or 0) for i in range(len(excessos))]
    somatorio = sum(corrigidos)
    
    html = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relatório de Fiscalização - {data['cabecalho'].get('mes_ano', '')}</title>
    <style>
        /* ============================================
           ESTILOS PARA IMPRESSÃO E TELA
           ============================================ */
        
        @page {{
            size: A4 portrait;
            margin: 10mm;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: Arial, sans-serif;
            font-size: 9px;
            line-height: 1.3;
            padding: 10px;
            background-color: #fff;
        }}
        
        /* Botão de impressão - só aparece na tela */
        .print-button {{
            position: fixed;
            top: 10px;
            right: 10px;
            padding: 12px 24px;
            background-color: #2c3e50;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            z-index: 1000;
        }}
        
        .print-button:hover {{
            background-color: #34495e;
        }}
        
        @media print {{
            .print-button {{
                display: none;
            }}
            
            body {{
                padding: 0;
            }}
        }}
        
        /* Tabelas */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 8px;
            page-break-inside: avoid;
        }}
        
        table, th, td {{
            border: 1px solid #2c3e50;
        }}
        
        th {{
            background-color: #34495e;
            color: white;
            padding: 6px;
            text-align: center;
            font-weight: bold;
            font-size: 9px;
        }}
        
        td {{
            padding: 5px;
            font-size: 9px;
        }}
        
        /* Classes utilitárias */
        .center {{ text-align: center; }}
        .right {{ text-align: right; }}
        .bold {{ font-weight: bold; }}
        
        .bg-yellow {{ background-color: #ffffcc; }}
        .bg-gray {{ background-color: #f0f0f0; }}
        .bg-pink {{ background-color: #ffccff; }}
        .bg-red {{ background-color: #ffcccc; }}
        
        .text-blue {{ color: #3498db; }}
        .text-red {{ color: #e74c3c; }}
        .text-green {{ color: #27ae60; }}
        
        /* Cabeçalho */
        .header-logo {{
            width: 100px;
            text-align: center;
            vertical-align: middle;
        }}
        
        .header-logo img {{
            max-width: 90px;
            max-height: 80px;
        }}
        
        .header-title {{
            text-align: center;
            font-weight: bold;
            font-size: 12px;
            padding: 8px;
        }}
        
        /* Células de informação */
        .info-label {{
            background-color: #f0f0f0;
            font-weight: bold;
            width: 180px;
        }}
        
        /* Tabela de ocorrências - células menores */
        .ocorrencias-table th {{
            font-size: 8px;
            padding: 4px 2px;
        }}
        
        .ocorrencias-table td {{
            font-size: 8px;
            padding: 3px 2px;
        }}
        
        /* Totalizadores */
        .totalizador-row {{
            font-size: 8px;
        }}
    </style>
</head>
<body>
    
    <!-- Botão de Impressão -->
    <button class="print-button" onclick="window.print()">
        🖨️ Imprimir / Gerar PDF
    </button>
    
    <!-- Cabeçalho -->
    <table>
        <tr>
            <td rowspan="2" class="header-logo">
                <img src="/static/img/logo_tjronovo.jpg" alt="Logo TJRO">
            </td>
            <td class="header-title">
                TRIBUNAL DE JUSTIÇA DO ESTADO DE RONDÔNIA
            </td>
        </tr>
        <tr>
            <td class="header-title" style="font-size: 11px;">
                RELATÓRIO DE OCORRÊNCIA - LISTA DE IMPERFEIÇÕES
            </td>
        </tr>
    </table>
    
    <!-- Informações do Contrato -->
    <table>
        <tr>
            <td class="info-label">Contrato</td>
            <td>{data['cabecalho'].get('contrato', '-')}</td>
        </tr>
        <tr>
            <td class="info-label">Protocolo</td>
            <td>{data['cabecalho'].get('protocolo', '-')}</td>
        </tr>
        <tr>
            <td class="info-label">Contratada</td>
            <td>{data['cabecalho'].get('contratada', '-')}</td>
        </tr>
        <tr>
            <td class="info-label">Objeto</td>
            <td>{data['cabecalho'].get('objeto', '-')}</td>
        </tr>
        <tr>
            <td class="info-label">Mês/ano de verificação</td>
            <td>{data['cabecalho'].get('mes_ano', '-')}</td>
        </tr>
    </table>
    
    <!-- Tabela de Ocorrências -->
    <table class="ocorrencias-table">
        <thead>
            <tr>
                <th colspan="12">OCORRÊNCIAS</th>
            </tr>
            <tr>
                <th style="width: 200px;">POSTO DE TRABALHO</th>
                <th style="width: 40px;">QTD</th>
    """
    
    for imp in imperfeicoes:
        html += f'<th style="width: 35px;" title="{imp.get("descricao", "")}">{str(imp.get("id", "")).zfill(2)}</th>'
    
    html += """
            </tr>
        </thead>
        <tbody>
    """
    
    # Postos
    for posto in postos:
        html += f"""
            <tr>
                <td>{posto.get('nome_posto', '-')}</td>
                <td class="center">{posto.get('qtd_motoristas_total', 0)}</td>
        """
        for i in range(1, 11):
            valor = posto.get('ocorrencias', {}).get(i, 0) or 0
            html += f'<td class="center">{valor}</td>'
        html += "</tr>"
    
    # Totalizadores
    html += '<tr class="bg-yellow bold totalizador-row"><td>Total (+)</td><td></td>'
    for t in totais:
        html += f'<td class="center">{t}</td>'
    html += '</tr>'
    
    html += '<tr class="totalizador-row"><td>Tolerância (-)</td><td></td>'
    for tol in tolerancias:
        html += f'<td class="center">{tol}</td>'
    html += '</tr>'
    
    html += '<tr class="totalizador-row"><td>Excesso Imperfeições (=)</td><td></td>'
    for exc in excessos:
        html += f'<td class="center">{exc}</td>'
    html += '</tr>'
    
    html += '<tr class="totalizador-row"><td>Multiplicador (x)</td><td></td>'
    for mult in multiplicadores:
        html += f'<td class="center">{mult}</td>'
    html += '</tr>'
    
    html += '<tr class="totalizador-row"><td>Número Corrigido (=)</td><td></td>'
    for corr in corrigidos:
        html += f'<td class="center">{corr}</td>'
    html += '</tr>'
    
    html += f"""
            <tr class="bg-yellow bold totalizador-row">
                <td colspan="11" class="right">Somatório dos Números Corrigidos (Fator de Aceitação)</td>
                <td class="center">{somatorio}</td>
            </tr>
        </tbody>
    </table>
    
    <!-- Faixas -->
    <table>
        <thead>
            <tr>
                <th>Faixa</th>
                <th>Fator de Aceitação</th>
                <th>Valor Mensal a Receber</th>
                <th>Percentual de Glosa</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for faixa in data.get('faixas', []):
        bg_class = 'bg-red' if faixa.get('nome') == data.get('faixa_alcancada') else ''
        html += f"""
            <tr class="{bg_class}">
                <td class="center">{faixa.get('nome', '-')}</td>
                <td class="center">{faixa.get('min', 0)} a {faixa.get('max', 0)}</td>
                <td class="center">{faixa.get('percentual_receber', 0)}% do Valor Mensal</td>
                <td class="center">{faixa.get('percentual_glosa', 0)}%</td>
            </tr>
        """
    
    html += f"""
        </tbody>
        <tfoot>
            <tr class="bg-yellow">
                <td colspan="4" class="center bold">
                    Faixa Alcançada no Mês de Referência: {data.get('faixa_alcancada', '-')}
                </td>
            </tr>
        </tfoot>
    </table>
    
    <!-- Informações de Glosa -->
    <table>
        <tr>
            <td class="info-label">Houve Glosa</td>
            <td class="center bold">{'SIM' if data.get('houve_glosa') else 'NÃO'}</td>
            <td rowspan="3" class="center bold" style="vertical-align: middle;">
                Fator Percentual de Recebimento e Remuneração de Serviços
            </td>
        </tr>
        <tr>
            <td class="info-label">Percentual de Glosa</td>
            <td class="center bold text-red" style="font-size: 14px;">
                {safe_float(data.get('percentual_glosa', 0)):.2f}%
            </td>
        </tr>
        <tr>
            <td class="info-label">Percentual do Total a Receber</td>
            <td class="center bold text-green bg-pink" style="font-size: 14px;">
                {safe_float(data.get('percentual_receber', 100)):.2f}%
            </td>
        </tr>
    </table>
    
    <!-- Localidades -->
    <table>
        <thead>
            <tr>
                <th rowspan="2">LOCALIDADE</th>
                <th rowspan="2" style="width: 50px;">POSTO</th>
                <th colspan="2">Valor de Referência</th>
                <th colspan="2">Valor Devido</th>
            </tr>
            <tr>
                <th style="width: 100px;">Valor Mensal</th>
                <th style="width: 100px;">Valor Total</th>
                <th style="width: 100px;">Valor Mensal</th>
                <th style="width: 100px;">Valor Total</th>
            </tr>
        </thead>
        <tbody>
    """
    
    total_postos = 0
    total_ref_mensal = 0.0
    total_ref_total = 0.0
    total_dev_mensal = 0.0
    total_dev_total = 0.0
    
    for loc in data.get('localidades', []):
        nome = f"{loc.get('nome', '-')} (*)" if loc.get('tem_asterisco') else loc.get('nome', '-')
        
        val_ref_mensal = safe_float(loc.get('valor_ref_mensal'))
        val_ref_total = safe_float(loc.get('valor_ref_total'))
        val_dev_mensal = safe_float(loc.get('valor_dev_mensal'))
        val_dev_total = safe_float(loc.get('valor_dev_total'))
        
        html += f"""
            <tr>
                <td>{nome}</td>
                <td class="center">{loc.get('qtd_posto', 0)}</td>
                <td class="right">{formatar_moeda(val_ref_mensal)}</td>
                <td class="right">{formatar_moeda(val_ref_total)}</td>
                <td class="right text-blue bold">{formatar_moeda(val_dev_mensal)}</td>
                <td class="right text-blue bold">{formatar_moeda(val_dev_total)}</td>
            </tr>
        """
        
        total_postos += loc.get('qtd_posto', 0)
        total_ref_mensal += val_ref_mensal
        total_ref_total += val_ref_total
        total_dev_mensal += val_dev_mensal
        total_dev_total += val_dev_total
    
    html += f"""
        </tbody>
        <tfoot style="background-color: #34495e; color: white;">
            <tr class="bold">
                <td class="right">TOTAL</td>
                <td class="center">{total_postos}</td>
                <td class="right">{formatar_moeda(total_ref_mensal)}</td>
                <td class="right">{formatar_moeda(total_ref_total)}</td>
                <td class="right">{formatar_moeda(total_dev_mensal)}</td>
                <td class="right">{formatar_moeda(total_dev_total)}</td>
            </tr>
        </tfoot>
    </table>
    
    <!-- Valores Finais -->
    <table style="width: 50%; margin-left: auto;">
        <tr>
            <td class="info-label">Valor Mensal a Receber</td>
            <td class="right bold text-green">
                {formatar_moeda(safe_float(data.get('totais', {}).get('valor_devido_total', 0)))}
            </td>
        </tr>
        <tr>
            <td class="info-label">Valor da Glosa</td>
            <td class="right bold text-red">
                {formatar_moeda(safe_float(data.get('totais', {}).get('valor_glosa', 0)))}
            </td>
        </tr>
    </table>
    
    <!-- Observações -->
    <table>
        <tr>
            <td class="info-label">Observações:</td>
        </tr>
        <tr>
            <td style="min-height: 60px; padding: 10px;">
    """
    
    if data.get('observacoes_parciais'):
        for obs in data['observacoes_parciais']:
            dias = obs.get('dias', 0)
            valor = safe_float(obs.get('valor', 0))
            html += f"{obs.get('posto', '-')} (*): {obs.get('nome', '-')} - {dias} dias trabalhados - {formatar_moeda(valor)}<br>"
    else:
        html += "&nbsp;"
    
    html += f"""
            </td>
        </tr>
    </table>
    
    <!-- Gestor e Unidade -->
    <table>
        <tr>
            <td class="info-label">Gestor do Contrato:</td>
            <td>{data['cabecalho'].get('gestor', '-')}</td>
        </tr>
        <tr>
            <td class="info-label">Unidade:</td>
            <td>{data['cabecalho'].get('unidade', '-')}</td>
        </tr>
    </table>
    
</body>
</html>
    """
    
    return html
	

def gerar_html_relatorio_pdf_simples(data):
    """HTML simplificado e otimizado para xhtml2pdf"""
    
    def formatar_moeda(valor):
        if valor is None:
            valor = 0.0
        return f"R$ {float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    def safe_float(val, default=0.0):
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    
    # Preparar dados
    imperfeicoes = data.get('imperfeicoes', [])[:10]
    postos = data.get('postos', [])
    
    # Calcular totais por coluna
    totais = [0] * 10
    for posto in postos:
        for i in range(1, 11):
            totais[i-1] += posto.get('ocorrencias', {}).get(i, 0) or 0
    
    # Calcular excessos e corrigidos
    tolerancias = [imp.get('tolerancia', 0) for imp in imperfeicoes]
    excessos = [max(0, totais[i] - (tolerancias[i] or 0)) for i in range(len(tolerancias))]
    multiplicadores = [imp.get('multiplicador', 0) for imp in imperfeicoes]
    corrigidos = [excessos[i] * (multiplicadores[i] or 0) for i in range(len(excessos))]
    somatorio = sum(corrigidos)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4 landscape;
                margin: 8mm;
            }}
            
            body {{
                font-family: Arial, sans-serif;
                font-size: 7px;
                line-height: 1.1;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 3px;
            }}
            
            td, th {{
                border: 1px solid #000;
                padding: 2px;
                vertical-align: middle;
            }}
            
            th {{
                background-color: #d0d0d0;
                font-weight: bold;
                text-align: center;
                font-size: 7px;
            }}
            
            .c {{ text-align: center; }}
            .r {{ text-align: right; }}
            .b {{ font-weight: bold; }}
            .bg1 {{ background-color: #ffffcc; }}
            .bg2 {{ background-color: #f0f0f0; }}
            .bg3 {{ background-color: #ffccff; }}
            .bg4 {{ background-color: #ffcccc; }}
        </style>
    </head>
    <body>
        
        <table>
            <tr>
                <td colspan="2" class="c b" style="font-size: 9px;">
                    TRIBUNAL DE JUSTIÇA DO ESTADO DE RONDÔNIA<br/>
                    RELATÓRIO DE OCORRÊNCIA - LISTA DE IMPERFEIÇÕES
                </td>
            </tr>
            <tr>
                <td class="bg2 b">Contrato</td>
                <td>{data['cabecalho'].get('contrato', '-')}</td>
            </tr>
            <tr>
                <td class="bg2 b">Protocolo</td>
                <td>{data['cabecalho'].get('protocolo', '-')}</td>
            </tr>
            <tr>
                <td class="bg2 b">Contratada</td>
                <td>{data['cabecalho'].get('contratada', '-')}</td>
            </tr>
            <tr>
                <td class="bg2 b">Objeto</td>
                <td>{data['cabecalho'].get('objeto', '-')}</td>
            </tr>
            <tr>
                <td class="bg2 b">Mês/Ano</td>
                <td>{data['cabecalho'].get('mes_ano', '-')}</td>
            </tr>
        </table>
        
        <table>
            <tr><th colspan="12">OCORRÊNCIAS</th></tr>
            <tr>
                <th>POSTO</th>
                <th>QTD</th>
    """
    
    for imp in imperfeicoes:
        html += f'<th>{str(imp.get("id", "")).zfill(2)}</th>'
    
    html += "</tr>"
    
    for posto in postos:
        html += f'<tr><td>{posto.get("nome_posto", "-")}</td><td class="c">{posto.get("qtd_motoristas_total", 0)}</td>'
        for i in range(1, 11):
            html += f'<td class="c">{posto.get("ocorrencias", {}).get(i, 0) or 0}</td>'
        html += '</tr>'
    
    html += '<tr class="bg1 b"><td>Total (+)</td><td></td>'
    for t in totais:
        html += f'<td class="c">{t}</td>'
    html += '</tr>'
    
    html += '<tr><td>Tolerância (-)</td><td></td>'
    for tol in tolerancias:
        html += f'<td class="c">{tol}</td>'
    html += '</tr>'
    
    html += '<tr><td>Excesso (=)</td><td></td>'
    for exc in excessos:
        html += f'<td class="c">{exc}</td>'
    html += '</tr>'
    
    html += '<tr><td>Multiplicador (x)</td><td></td>'
    for mult in multiplicadores:
        html += f'<td class="c">{mult}</td>'
    html += '</tr>'
    
    html += '<tr><td>Corrigido (=)</td><td></td>'
    for corr in corrigidos:
        html += f'<td class="c">{corr}</td>'
    html += '</tr>'
    
    html += f'<tr class="bg1 b"><td colspan="11" class="r">Somatório (Fator de Aceitação)</td><td class="c">{somatorio}</td></tr>'
    html += '</table>'
    
    html += '<table><tr><th>Faixa</th><th>Fator</th><th>% Receber</th><th>% Glosa</th></tr>'
    
    for faixa in data.get('faixas', []):
        bg = 'bg4' if faixa.get('nome') == data.get('faixa_alcancada') else ''
        html += f'<tr class="{bg}"><td class="c">{faixa.get("nome", "-")}</td>'
        html += f'<td class="c">{faixa.get("min", 0)} a {faixa.get("max", 0)}</td>'
        html += f'<td class="c">{faixa.get("percentual_receber", 0)}%</td>'
        html += f'<td class="c">{faixa.get("percentual_glosa", 0)}%</td></tr>'
    
    html += f'<tr class="bg1 b"><td colspan="4" class="c">Faixa Alcançada: {data.get("faixa_alcancada", "-")}</td></tr>'
    html += '</table>'
    
    html += '<table>'
    html += f'<tr><td class="bg2 b">Houve Glosa</td><td class="c b">{"SIM" if data.get("houve_glosa") else "NÃO"}</td></tr>'
    html += f'<tr><td class="bg2 b">% Glosa</td><td class="c b">{safe_float(data.get("percentual_glosa", 0)):.2f}%</td></tr>'
    html += f'<tr><td class="bg2 b">% Total a Receber</td><td class="c b bg3">{safe_float(data.get("percentual_receber", 100)):.2f}%</td></tr>'
    html += '</table>'
    
    html += '<table><tr><th>LOCALIDADE</th><th>QTD</th><th>Ref.Mensal</th><th>Ref.Total</th><th>Dev.Mensal</th><th>Dev.Total</th></tr>'
    
    total_postos = 0
    total_ref_mensal = 0.0
    total_ref_total = 0.0
    total_dev_mensal = 0.0
    total_dev_total = 0.0
    
    for loc in data.get('localidades', []):
        nome = f"{loc.get('nome', '-')} (*)" if loc.get('tem_asterisco') else loc.get('nome', '-')
        
        val_ref_mensal = safe_float(loc.get('valor_ref_mensal'))
        val_ref_total = safe_float(loc.get('valor_ref_total'))
        val_dev_mensal = safe_float(loc.get('valor_dev_mensal'))
        val_dev_total = safe_float(loc.get('valor_dev_total'))
        
        html += f'<tr><td>{nome}</td><td class="c">{loc.get("qtd_posto", 0)}</td>'
        html += f'<td class="r">{formatar_moeda(val_ref_mensal)}</td>'
        html += f'<td class="r">{formatar_moeda(val_ref_total)}</td>'
        html += f'<td class="r b">{formatar_moeda(val_dev_mensal)}</td>'
        html += f'<td class="r b">{formatar_moeda(val_dev_total)}</td></tr>'
        
        total_postos += loc.get('qtd_posto', 0)
        total_ref_mensal += val_ref_mensal
        total_ref_total += val_ref_total
        total_dev_mensal += val_dev_mensal
        total_dev_total += val_dev_total
    
    html += f'<tr class="b"><td class="r">TOTAL</td><td class="c">{total_postos}</td>'
    html += f'<td class="r">{formatar_moeda(total_ref_mensal)}</td>'
    html += f'<td class="r">{formatar_moeda(total_ref_total)}</td>'
    html += f'<td class="r">{formatar_moeda(total_dev_mensal)}</td>'
    html += f'<td class="r">{formatar_moeda(total_dev_total)}</td></tr>'
    html += '</table>'
    
    html += '<table>'
    html += f'<tr><td class="bg2 b">Valor a Receber</td><td class="r b">{formatar_moeda(safe_float(data.get("totais", {}).get("valor_devido_total", 0)))}</td></tr>'
    html += f'<tr><td class="bg2 b">Valor da Glosa</td><td class="r b">{formatar_moeda(safe_float(data.get("totais", {}).get("valor_glosa", 0)))}</td></tr>'
    html += '</table>'
    
    html += '<table><tr><td class="bg2 b">Observações</td><td>'
    
    if data.get('observacoes_parciais'):
        for obs in data['observacoes_parciais']:
            dias = obs.get('dias', 0)
            valor = safe_float(obs.get('valor', 0))
            html += f"{obs.get('posto', '-')} (*): {obs.get('nome', '-')} - {dias} dias - {formatar_moeda(valor)}<br/>"
    else:
        html += "&nbsp;"
    
    html += '</td></tr>'
    html += f'<tr><td class="bg2 b">Gestor</td><td>{data["cabecalho"].get("gestor", "-")}</td></tr>'
    html += f'<tr><td class="bg2 b">Unidade</td><td>{data["cabecalho"].get("unidade", "-")}</td></tr>'
    html += '</table>'
    
    html += '</body></html>'
    
    return html


# ============================================================
# ROTAS COMPLETAS CORRIGIDAS - PROTEÇÃO CONTRA NULL/NONE
# COPIAR E COLAR DIRETO NO app.py
# ============================================================
# ADICIONAR LOGO APÓS A ROTA /relatorio-fiscalizacao-impressao
# ============================================================

# ============================================================
# ROTA 1 - GERAR DADOS DO RELATÓRIO DE RETENÇÃO
# ============================================================
@app.route('/api/gestao-terceirizados/relatorio-retencao', methods=['POST'])
@login_required
def api_gerar_relatorio_retencao():
    """Gera o relatório de retenção em conta vinculada"""
    try:
        data = request.get_json()
        id_contrato = data.get('id_contrato')
        mes = data.get('mes')
        ano = data.get('ano')
        
        if not all([id_contrato, mes, ano]):
            return jsonify({
                'success': False,
                'error': 'Parâmetros incompletos'
            })
        
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Buscar dados do cabeçalho
        cursor.execute("""
            SELECT 
                c.CONTRATO,
                g.PROCESSO,
                f.NM_FORNECEDOR,
                c.SETOR_GESTOR,
                c.NOME_GESTOR,
                c.ID_RAT,
                r.PC_13,
                r.PC_FERIAS,
                r.PC_MULTA_FGTS,
                r.PC_INCIDENCIAS
            FROM GESTAO_CONTRATOS_TERCEIRIZADOS c
            LEFT JOIN CAD_FORNECEDOR f ON c.ID_FORNECEDOR = f.ID_FORNECEDOR
			LEFT JOIN GESTAO_CONTRATOS_EXERCICIOS g ON g.ID_CONTRATO = c.ID_CONTRATO
            LEFT JOIN PARAMETRO_RETENCAO_CONTA_VINCULADA r ON c.ID_RAT = r.ID_RAT
            WHERE c.ID_CONTRATO = %s
        """, (id_contrato,))
        
        contrato = cursor.fetchone()
        
        if not contrato:
            cursor.close()
            return jsonify({
                'success': False,
                'error': 'Contrato não encontrado'
            })
        
        # Verificar se tem ID_RAT configurado
        if not contrato['ID_RAT']:
            cursor.close()
            return jsonify({
                'success': False,
                'error': 'Contrato sem ID_RAT configurado. Configure os parâmetros de retenção primeiro.'
            })
        
        # Calcular percentual total (com proteção contra None)
        pc_13 = float(contrato['PC_13'] or 0)
        pc_ferias = float(contrato['PC_FERIAS'] or 0)
        pc_fgts = float(contrato['PC_MULTA_FGTS'] or 0)
        pc_incidencias = float(contrato['PC_INCIDENCIAS'] or 0)
        pc_total = pc_13 + pc_ferias + pc_fgts + pc_incidencias
        
        # Calcular primeiro e último dia do mês
        from calendar import monthrange
        from datetime import datetime, date
        
        ano_int = int(ano)
        meses = {
            'JANEIRO': 1, 'FEVEREIRO': 2, 'MARÇO': 3, 'ABRIL': 4,
            'MAIO': 5, 'JUNHO': 6, 'JULHO': 7, 'AGOSTO': 8,
            'SETEMBRO': 9, 'OUTUBRO': 10, 'NOVEMBRO': 11, 'DEZEMBRO': 12
        }
        mes_numero = meses.get(mes.upper())
        
        if not mes_numero:
            cursor.close()
            return jsonify({'success': False, 'error': 'Mês inválido'}), 400
        
        primeiro_dia = datetime(ano_int, mes_numero, 1).date()
        ultimo_dia = datetime(ano_int, mes_numero, monthrange(ano_int, mes_numero)[1]).date()
        total_dias_mes = ultimo_dia.day
        
        # ✅ BUSCAR POSTOS COM MOTORISTAS E SEUS PERÍODOS (AGRUPADOS)
        # Seguir mesma lógica do relatório de fiscalização
        cursor.execute("""
            SELECT 
                p.ID_POSTO,
                p.DE_POSTO,
                pv.VL_MENSAL,
                pv.VL_SALARIO
            FROM POSTO_TRABALHO p
            LEFT JOIN POSTO_TRABALHO_VALORES pv ON p.ID_POSTO = pv.ID_POSTO
                AND pv.DT_INICIO <= %s
                AND (pv.DT_FIM IS NULL OR pv.DT_FIM >= %s)
            WHERE p.ID_CONTRATO = %s
            ORDER BY p.DE_POSTO
        """, (ultimo_dia, primeiro_dia, id_contrato))
        
        postos = cursor.fetchall()
        
        if not postos:
            cursor.close()
            return jsonify({
                'success': False,
                'error': 'Nenhum posto encontrado'
            })
        
        # Processar cada posto
        postos_processados = []
        
        for posto in postos:
            id_posto = posto['ID_POSTO']
            de_posto = posto['DE_POSTO']
            vl_salario = float(posto['VL_SALARIO'] or 0)
            vl_mensal = float(posto['VL_MENSAL'] or 0)
            
            if vl_salario == 0 or vl_mensal == 0:
                continue
            
            # Buscar motoristas do posto
            cursor.execute("""
                SELECT DISTINCT v.ID_MOTORISTA
                FROM POSTO_TRABALHO_VINCULO v
                INNER JOIN CAD_MOTORISTA_PERIODOS p ON v.ID_MOTORISTA = p.ID_MOTORISTA
                WHERE v.ID_POSTO = %s
                AND p.DT_INICIO <= %s
                AND (p.DT_FIM IS NULL OR p.DT_FIM >= %s)
            """, (id_posto, ultimo_dia, primeiro_dia))
            
            motoristas_ids = cursor.fetchall()
            
            motoristas_completo = []
            motoristas_parcial = []
            
            for mot in motoristas_ids:
                id_motorista = mot['ID_MOTORISTA']
                
                # ✅ Buscar TODOS os períodos do motorista no mês
                cursor.execute("""
                    SELECT DT_INICIO, DT_FIM
                    FROM CAD_MOTORISTA_PERIODOS
                    WHERE ID_MOTORISTA = %s
                    AND DT_INICIO <= %s
                    AND (DT_FIM IS NULL OR DT_FIM >= %s)
                    ORDER BY DT_INICIO
                """, (id_motorista, ultimo_dia, primeiro_dia))
                
                periodos = cursor.fetchall()
                
                if periodos:
                    # Verificar se tem período que cobre o mês completo
                    tem_mes_completo = False
                    for periodo in periodos:
                        dt_inicio = periodo['DT_INICIO']
                        dt_fim = periodo['DT_FIM']
                        
                        if dt_inicio <= primeiro_dia and (dt_fim is None or dt_fim >= ultimo_dia):
                            tem_mes_completo = True
                            break
                    
                    if tem_mes_completo:
                        motoristas_completo.append({
                            'id_motorista': id_motorista,
                            'dias_trabalhados': total_dias_mes
                        })
                    else:
                        # ✅ SOMAR dias de TODOS os períodos (igual fiscalização)
                        total_dias = 0
                        
                        for periodo in periodos:
                            dt_inicio = periodo['DT_INICIO']
                            dt_fim = periodo['DT_FIM']
                            
                            # Ajustar para os limites do mês
                            inicio_calculo = max(dt_inicio, primeiro_dia)
                            fim_calculo = min(dt_fim if dt_fim else ultimo_dia, ultimo_dia)
                            
                            # Calcular dias deste período
                            dias_periodo = (fim_calculo - inicio_calculo).days + 1
                            total_dias += dias_periodo
                        
                        # Buscar nome do motorista
                        cursor.execute("SELECT NM_MOTORISTA FROM CAD_MOTORISTA WHERE ID_MOTORISTA = %s", (id_motorista,))
                        nome_result = cursor.fetchone()
                        nome_motorista = nome_result['NM_MOTORISTA'] if nome_result else 'Não identificado'
                        
                        motoristas_parcial.append({
                            'id_motorista': id_motorista,
                            'nome_motorista': nome_motorista,
                            'dias_trabalhados': total_dias
                        })
            
            # Adicionar ao resultado
            postos_processados.append({
                'id_posto': id_posto,
                'de_posto': de_posto,
                'vl_salario': vl_salario,
                'vl_mensal': vl_mensal,
                'motoristas_completo': motoristas_completo,
                'motoristas_parcial': motoristas_parcial
            })
        
        # Montar os quadros
        quadro1 = []
        quadro2 = []
        observacoes = []
        
        for posto in postos_processados:
            vl_salario = posto['vl_salario']
            vl_mensal = posto['vl_mensal']
            de_posto = posto['de_posto']
            
            # Motoristas que trabalharam o mês completo
            if posto['motoristas_completo']:
                qtd = len(posto['motoristas_completo'])
                
                # Calcular retenções com valor integral
                ret_13 = vl_salario * pc_13 / 100
                ret_ferias = vl_salario * pc_ferias / 100
                ret_fgts = vl_salario * pc_fgts / 100
                ret_incidencias = vl_salario * pc_incidencias / 100
                ret_total = ret_13 + ret_ferias + ret_fgts + ret_incidencias
                
                quadro1.append({
                    'de_posto': de_posto,
                    'vl_salario': vl_salario,
                    'ret_13': ret_13,
                    'ret_ferias': ret_ferias,
                    'ret_fgts': ret_fgts,
                    'ret_incidencias': ret_incidencias,
                    'ret_total': ret_total
                })
                
                quadro2.append({
                    'de_posto': de_posto,
                    'vl_mensal': vl_mensal,
                    'qtd_postos': qtd,
                    'qtd_por_posto': 1,
                    'qtd_total_func': qtd,
                    'vl_mensal_total': vl_mensal * qtd,
                    'ret_unitario': ret_total,
                    'ret_total': ret_total * qtd
                })
            
            # ✅ Motoristas parciais - UMA LINHA POR MOTORISTA (com dias somados)
            for mot_parcial in posto['motoristas_parcial']:
                dias_trab = mot_parcial['dias_trabalhados']
                nome_mot = mot_parcial['nome_motorista']
                
                # Calcular valores proporcionais (divisão por 30)
                vl_salario_proporcional = (vl_salario / 30) * dias_trab
                vl_mensal_proporcional = (vl_mensal / 30) * dias_trab
                
                # Calcular retenções
                ret_13 = vl_salario_proporcional * pc_13 / 100
                ret_ferias = vl_salario_proporcional * pc_ferias / 100
                ret_fgts = vl_salario_proporcional * pc_fgts / 100
                ret_incidencias = vl_salario_proporcional * pc_incidencias / 100
                ret_total = ret_13 + ret_ferias + ret_fgts + ret_incidencias
                
                quadro1.append({
                    'de_posto': de_posto + ' (*)',
                    'vl_salario': vl_salario_proporcional,
                    'ret_13': ret_13,
                    'ret_ferias': ret_ferias,
                    'ret_fgts': ret_fgts,
                    'ret_incidencias': ret_incidencias,
                    'ret_total': ret_total
                })
                
                quadro2.append({
                    'de_posto': de_posto + ' (*)',
                    'vl_mensal': vl_mensal_proporcional,
                    'qtd_postos': 1,
                    'qtd_por_posto': 1,
                    'qtd_total_func': 1,
                    'vl_mensal_total': vl_mensal_proporcional,
                    'ret_unitario': ret_total,
                    'ret_total': ret_total
                })
                
                # Observação
                obs = f"{de_posto} (*): {nome_mot} - {dias_trab} dias trabalhados - R$ {vl_mensal_proporcional:.2f}"
                observacoes.append(obs)
        
        # Retornar JSON
        resultado = {
            'success': True,
            'data': {
                'cabecalho': {
                    'contrato': contrato['CONTRATO'],
                    'protocolo': contrato['PROCESSO'],
                    'contratada': contrato['NM_FORNECEDOR'],
                    'mes_ano': f"{mes}/{ano}",
                    'gestor': contrato['NOME_GESTOR'],
                    'unidade': contrato['SETOR_GESTOR'],
                    'id_rat': contrato['ID_RAT'],
                    'pc_13': pc_13,
                    'pc_ferias': pc_ferias,
                    'pc_fgts': pc_fgts,
                    'pc_incidencias': pc_incidencias,
                    'pc_total': pc_total
                },
                'quadro1': quadro1,
                'quadro2': quadro2,
                'observacoes': observacoes
            }
        }
        
        cursor.close()
        return jsonify(resultado)
        
    except Exception as e:
        print(f"Erro ao gerar relatório de retenção: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })

# ============================================================
# ROTA 2 - PÁGINA DE IMPRESSÃO
# ============================================================
@app.route('/relatorio-retencao-impressao')
@login_required
def relatorio_retencao_impressao():
    """Página separada para impressão do relatório de retenção"""
    return render_template('rel_retencao_contavinculada.html')


if __name__ == '__main__':

    socketio.run(app, host='0.0.0.0', port=5000, debug=True)







