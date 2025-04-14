from flask import Flask, render_template, request, make_response, redirect, url_for, flash, jsonify, send_file, session
from flask_mail import Mail, Message
from functools import wraps
import os
from flask_mysqldb import MySQL
import MySQLdb.cursors
import uuid
import base64
from datetime import datetime
from io import BytesIO
from pytz import timezone

app = Flask(__name__)

# Configuração do Flask-Mail
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')  # Substitua pelo seu servidor SMTP
app.config['MAIL_PORT'] = os.getenv('MAIL_PORT') 
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME') 
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD') 
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
app.config['MAIL_USE_TLS'] = True 
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_MAX_EMAILS'] = None
app.config['MAIL_TIMEOUT'] = 10  # segundos
mail = Mail(app)

# Configuração do MySQL
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')
mysql = MySQL(app)

# Configuração para segurança
app.secret_key = os.getenv('SECRET_KEY')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_logado' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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
    
    # Criptografa a senha para comparação
    senha_criptografada = criptografar(senha)
    
    # Busca o usuário no banco de dados
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT ID_USUARIO, NM_USUARIO, NIVEL_ACESSO 
        FROM TJ_USUARIO 
        WHERE US_LOGIN = %s 
        AND SENHA = %s 
        AND FL_STATUS = 'A'
    """, (login, senha_criptografada))
    
    usuario = cur.fetchone()
    cur.close()
    
    if usuario:
        # Usuário encontrado e senha correta
        session['usuario_logado'] = True
        session['usuario_id'] = usuario[0]
        session['usuario_login'] = login
        session['usuario_nome'] = usuario[1]
        session['nivel_acesso'] = usuario[2]
        
        # Retorna dados para salvar no localStorage via JavaScript
        return jsonify({
            'sucesso': True,
            'usuario_id': usuario[0],
            'usuario_login': login,
            'usuario_nome': usuario[1],
            'nivel_acesso': usuario[2]
        })
    else:
        # Usuário não encontrado ou credenciais inválidas
        flash('Credenciais inválidas. Tente novamente.', 'danger')
        return jsonify({'sucesso': False, 'mensagem': 'Credenciais inválidas'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/nova_vistoria')
def nova_vistoria():
    # Busca motoristas e veículos do banco de dados
    cur = mysql.connection.cursor()
    cur.execute("SELECT ID_MOTORISTA, NM_MOTORISTA FROM TJ_MOTORISTA WHERE ID_MOTORISTA <> 0 ORDER BY NM_MOTORISTA")
    motoristas = cur.fetchall()
    cur.execute("SELECT ID_VEICULO, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO FROM TJ_VEICULO WHERE ATIVO = 'S' AND FL_ATENDIMENTO = 'S' ORDER BY DS_MODELO, NU_PLACA")
    veiculos = cur.fetchall()
    cur.close()
    
    return render_template('nova_vistoria.html', motoristas=motoristas, veiculos=veiculos, tipo='SAIDA')


@app.route('/nova_vistoria2')
def nova_vistoria2():
    # Busca motoristas e veículos do banco de dados
    cur = mysql.connection.cursor()
    cur.execute("SELECT ID_MOTORISTA, NM_MOTORISTA FROM TJ_MOTORISTA WHERE ID_MOTORISTA <> 0 ORDER BY NM_MOTORISTA")
    motoristas = cur.fetchall()
    cur.execute("SELECT ID_VEICULO, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO FROM TJ_VEICULO WHERE ATIVO = 'S' AND FL_ATENDIMENTO = 'S' ORDER BY DS_MODELO, NU_PLACA")
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
               v.ASS_USUARIO, v.ASS_MOTORISTA, v.OBS
        FROM VISTORIAS v
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
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
            tipo='INICIAL'
        )
    else:
        return redirect(url_for('ver_vistoria2', id=id))
       


@app.route('/nova_vistoria_devolucao/<int:vistoria_saida_id>')
def nova_vistoria_devolucao(vistoria_saida_id):
    # Buscar informações da vistoria de saida
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT v.IDVISTORIA, v.IDMOTORISTA, v.IDVEICULO, m.NM_MOTORISTA, ve.NU_PLACA, v.COMBUSTIVEL
        FROM VISTORIAS v
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
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
        tipo='DEVOLUCAO'
    )

@app.route('/salvar_vistoria', methods=['POST'])
def salvar_vistoria():
    try:
        # Obter dados do formulário
        id_motorista = request.form['id_motorista']
        id_veiculo = request.form['id_veiculo']
        tipo = request.form['tipo']
        vistoria_saida_id = request.form.get('vistoria_saida_id')
        combustivel = request.form['combustivel']
        hodometro = request.form['hodometro']
        obs = request.form['observacoes']
        
        # Obter o nome do usuário da sessão
        usuario_nome = session.get('usuario_nome', 'Sistema')

        # Obter as assinaturas
        assinatura_usuario_data = request.form.get('assinatura_usuario')
        assinatura_motorista_data = request.form.get('assinatura_motorista')
        
        # Processar as assinaturas de base64 para binário, se existirem
        assinatura_usuario_bin = None
        assinatura_motorista_bin = None
        
        if assinatura_usuario_data and ',' in assinatura_usuario_data:
            assinatura_usuario_data = assinatura_usuario_data.split(',')[1]
            assinatura_usuario_bin = base64.b64decode(assinatura_usuario_data)
        
        if assinatura_motorista_data and ',' in assinatura_motorista_data:
            assinatura_motorista_data = assinatura_motorista_data.split(',')[1]
            assinatura_motorista_bin = base64.b64decode(assinatura_motorista_data)
        
        # Criar uma nova vistoria
        cur = mysql.connection.cursor()
        
        # Capturar o último ID antes da inserção
        cur.execute("SELECT MAX(IDVISTORIA) FROM VISTORIAS")
        ultimo_id = cur.fetchone()[0] or 0

        data_e_hora_atual = datetime.now()
        fuso_horario = timezone('America/Manaus')
        data_hora = data_e_hora_atual.astimezone(fuso_horario)
        #data_pagamento = data_e_hora_manaus.strftime('%d/%m/%Y %H:%M')        
    
        if tipo == 'SAIDA':
            # Para vistorias de SAIDA, definir status como EM_TRANSITO
            cur.execute(
                """INSERT INTO VISTORIAS 
                   (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, COMBUSTIVEL, HODOMETRO, ASS_USUARIO, ASS_MOTORISTA, OBS, USUARIO) 
                   VALUES (%s, %s, %s, %s, 'EM_TRANSITO', %s, %s, %s, %s, %s, %s)""",
                (id_motorista, id_veiculo, data_hora, tipo, combustivel, hodometro, assinatura_usuario_bin, assinatura_motorista_bin, obs, usuario_nome)
            )
        else:  # DEVOLUCAO
            # Para vistorias de DEVOLUCAO, definir status como FINALIZADA
            cur.execute(
                """INSERT INTO VISTORIAS 
                   (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, VISTORIA_SAIDA_ID, COMBUSTIVEL, HODOMETRO, ASS_USUARIO, ASS_MOTORISTA, OBS, USUARIO) 
                   VALUES (%s, %s, %s, %s, 'FINALIZADA', %s, %s, %s, %s, %s, %s, %s)""",
                (id_motorista, id_veiculo, data_hora, tipo, vistoria_saida_id, combustivel, hodometro, assinatura_usuario_bin, assinatura_motorista_bin, obs, usuario_nome)
            )
            # Atualizar status da vistoria de saida para finalizada
            cur.execute(
                "UPDATE VISTORIAS SET STATUS = 'FINALIZADA' WHERE IDVISTORIA = %s",
                (vistoria_saida_id,)
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
        
        # Debug: Verificar recebimento das fotos
        fotos = request.files.getlist('fotos[]')
        detalhamentos = request.form.getlist('detalhamentos[]')
        
        print(f"Tipo de vistoria: {tipo}")
        print(f"Número de fotos recebidas: {len(fotos)}")
        print(f"Número de detalhamentos recebidos: {len(detalhamentos)}")
        
        # Processar todas as fotos de uma vez
        for i, foto in enumerate(fotos):
            if foto:  # Apenas verificar se o objeto de arquivo existe
                try:
                    # Ler o conteúdo binário da imagem
                    foto_data = foto.read()
                    
                    detalhamento = detalhamentos[i] if i < len(detalhamentos) else ""
                    
                    # Inserir explicitamente o conteúdo binário da imagem com o ID da vistoria confirmado
                    print(f"Inserindo item {i} para vistoria {id_vistoria}")
                    
                    # VERIFICAÇÃO EXTRA: Confirmar que a vistoria existe antes de inserir
                    cur.execute("SELECT 1 FROM VISTORIAS WHERE IDVISTORIA = %s", (id_vistoria,))
                    if not cur.fetchone():
                        print(f"ALERTA: Vistoria com ID {id_vistoria} não encontrada!")
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
                        print(f"ALERTA: Item inserido com IDVISTORIA incorreto: {item_result[0]} != {id_vistoria}")
                        
                except Exception as e:
                    print(f"Erro ao processar foto {i}: {str(e)}")
        
        cur.close()
        flash('Vistoria salva com sucesso!', 'success')
        return redirect(url_for('index'))
    
    except Exception as e:
        print(f"ERRO CRÍTICO: {str(e)}")
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
                (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, COMBUSTIVEL, HODOMETRO, OBS, USUARIO) 
                VALUES (%s, %s, %s, %s, 'EM_TRANSITO', %s, %s, %s, %s)""",
            (id_motorista, id_veiculo, data_hora, tipo, combustivel, hodometro, obs, usuario_nome)
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
        SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, 
        CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
        v.DATA, v.TIPO, v.STATUS, v.OBS 
        FROM VISTORIAS v
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.STATUS = 'EM_TRANSITO' AND v.TIPO = 'SAIDA'
        ORDER BY v.DATA DESC
    """)
    vistorias_em_transito = cur.fetchall()

    # Buscar vistorias em Pendentes
    cur.execute("""
        SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, 
        CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO,
        v.DATA, v.TIPO, v.STATUS, v.OBS 
        FROM VISTORIAS v
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.TIPO IN ('INICIAL', 'CONFIRMACAO')
        ORDER BY v.DATA DESC
    """)
    vistorias_pendentes = cur.fetchall()

    # Buscar vistorias finalizadas (Saidas com devolução ou devoluções)
    cur.execute("""
        SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, 
        CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
        v.DATA, v.TIPO, v.STATUS, v.OBS, 
        (SELECT IDVISTORIA FROM VISTORIAS WHERE VISTORIA_SAIDA_ID = v.IDVISTORIA) AS ID_DEVOLUCAO
        FROM VISTORIAS v
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
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
            SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO, 
                   v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO,
                   v.VISTORIA_SAIDA_ID, v.ASS_USUARIO, v.ASS_MOTORISTA, v.HODOMETRO, v.OBS, v.USUARIO
            FROM VISTORIAS v
            JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
            JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
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
                    SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
                           v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO,
                           v.VISTORIA_SAIDA_ID, v.ASS_USUARIO, v.ASS_MOTORISTA, v.HODOMETRO, v.OBS, v.USUARIO
                    FROM VISTORIAS v
                    JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
                    JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
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
                    SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
                           v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO,
                           v.VISTORIA_SAIDA_ID, v.ASS_USUARIO, v.ASS_MOTORISTA, v.HODOMETRO, v.OBS, v.USUARIO
                    FROM VISTORIAS v
                    JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
                    JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
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
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
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
        cursor.execute("SELECT SIGLA_SETOR FROM TJ_SETORES ORDER BY SIGLA_SETOR")
        setores = [{'sigla': row[0]} for row in cursor.fetchall()]
        cursor.close()
        return jsonify(setores)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/motoristas')
@login_required
def listar_motoristas():
    try:
        nome = request.args.get('nome', '')
        cursor = mysql.connection.cursor()
        
        if nome:
            query = """
            SELECT 
                ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, 
                ORDEM_LISTA AS TIPO_CADASTRO, SIGLA_SETOR,
                FILE_PDF IS NOT NULL AS FILE_PDF
            FROM TJ_MOTORISTA 
            WHERE ID_MOTORISTA > 0
            AND CONCAT(CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, SIGLA_SETOR) LIKE %s 
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query, (f'%{nome}%',))
        else:
            query = """
            SELECT 
                ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, 
                ORDEM_LISTA AS TIPO_CADASTRO, SIGLA_SETOR,
                FILE_PDF IS NOT NULL AS FILE_PDF
            FROM TJ_MOTORISTA
            WHERE ID_MOTORISTA > 0 
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query)
        
        columns = ['id_motorista', 'cad_motorista', 'nm_motorista', 'tipo_cadastro', 'sigla_setor', 'file_pdf']
        motoristas = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        return jsonify(motoristas)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/motoristas/<int:id_motorista>')
@login_required
def detalhe_motorista(id_motorista):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT 
            ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, ORDEM_LISTA, 
            SIGLA_SETOR, CAT_CNH, DT_VALIDADE_CNH, ULTIMA_ATUALIZACAO, 
            NU_TELEFONE, OBS_MOTORISTA, ATIVO, ORDEM_LISTA, NOME_ARQUIVO, EMAIL
        FROM TJ_MOTORISTA 
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
                'tipo_cadastro_desc': result[11],
                'nome_arquivo': result[12],
                'email': result[13]
            }
            return jsonify(motorista)
        else:
            return jsonify({'erro': 'Motorista não encontrado'}), 404
    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/api/motoristas/cadastrar', methods=['POST'])
@login_required
def cadastrar_motorista():

    tipo_cad = {
        1: 'Administrativo',
        2: 'Motorista Desembargador',
        3: 'Motorista Atendimento',
        4: 'Cadastro de Condutores'
    }

    try:

        cursor = mysql.connection.cursor()
        
        # Get last ID and increment
        cursor.execute("SELECT COALESCE(MAX(ID_MOTORISTA), 0) + 1 FROM TJ_MOTORISTA")
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
        INSERT INTO TJ_MOTORISTA (
            ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, 
            SIGLA_SETOR, CAT_CNH, DT_VALIDADE_CNH, ULTIMA_ATUALIZACAO, 
            NU_TELEFONE, OBS_MOTORISTA, ATIVO, USUARIO, DT_TRANSACAO, 
            FILE_PDF, NOME_ARQUIVO, ORDEM_LISTA, EMAIL
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'S', %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            novo_id, cad_motorista, nm_motorista, tipo_cadastro_desc, 
            sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
            nu_telefone, obs_motorista, session.get('usuario_id'), 
            dt_transacao, file_blob, nome_arquivo, tipo_cadastro, email
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'sucesso': True, 'id_motorista': novo_id})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500

@app.route('/api/motoristas/atualizar', methods=['POST'])
@login_required
def atualizar_motorista():

    tipo_cad = {
        1: 'Administrativo',
        2: 'Motorista Desembargador',
        3: 'Motorista Atendimento',
        4: 'Cadastro de Condutores'
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
            UPDATE TJ_MOTORISTA 
            SET CAD_MOTORISTA = %s, NM_MOTORISTA = %s, TIPO_CADASTRO = %s, 
                SIGLA_SETOR = %s, CAT_CNH = %s, DT_VALIDADE_CNH = %s, 
                ULTIMA_ATUALIZACAO = %s, NU_TELEFONE = %s, OBS_MOTORISTA = %s, 
                ATIVO = %s, USUARIO = %s, DT_TRANSACAO = %s, 
                FILE_PDF = %s, NOME_ARQUIVO = %s, ORDEM_LISTA = %s, EMAIL = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                dt_transacao, file_blob, nome_arquivo, tipo_cadastro, email, id_motorista
            ))
        else:
            # Update without changing file
            query = """
            UPDATE TJ_MOTORISTA 
            SET CAD_MOTORISTA = %s, NM_MOTORISTA = %s, TIPO_CADASTRO = %s, 
                SIGLA_SETOR = %s, CAT_CNH = %s, DT_VALIDADE_CNH = %s, 
                ULTIMA_ATUALIZACAO = %s, NU_TELEFONE = %s, OBS_MOTORISTA = %s, 
                ATIVO = %s, USUARIO = %s, DT_TRANSACAO = %s, ORDEM_LISTA = %s, EMAIL = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                dt_transacao, tipo_cadastro, email, id_motorista
            ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'sucesso': True, 'id_motorista': id_motorista})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'sucesso': False, 'mensagem': str(e)}), 500

@app.route('/api/motoristas/download_cnh/<int:id_motorista>')
@login_required
def download_cnh(id_motorista):
    try:
        cursor = mysql.connection.cursor()
        query = "SELECT FILE_PDF, NOME_ARQUIVO FROM TJ_MOTORISTA WHERE ID_MOTORISTA = %s"
        cursor.execute(query, (id_motorista,))
        result = cursor.fetchone()
        cursor.close()

        if result and result[0]:
            return send_file(
                BytesIO(result[0]),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=result[1]
            )
        else:
            return "Arquivo não encontrado", 404
    except Exception as e:
        return str(e), 500


@app.route('/controle_locacoes')
@login_required
def controle_locacoes():
    return render_template('controle_locacoes.html')

@app.route('/api/processos_locacao')
@login_required
def api_processos_locacao():
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT cl.ID_CL, cl.ANO_EXERCICIO,
               f.NM_FORNECEDOR, cl.NU_SEI, cl.NU_CONTRATO
        FROM TJ_CONTROLE_LOCACAO cl, TJ_FORNECEDOR f
        WHERE f.ID_FORNECEDOR = cl.ID_FORNECEDOR
        AND cl.ATIVO = 'S'
        """
        cursor.execute(query)
        processos = cursor.fetchall()
        
        # Converter para dicionários para facilitar o uso no JSON
        resultado = []
        for processo in processos:
            resultado.append({
                'ID_CL': processo[0],
                'ANO_EXERCICIO': processo[1],
                'NM_FORNECEDOR': processo[2],
                'NU_SEI': processo[3],
                'NU_CONTRATO': processo[4]
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
        SELECT e.ID_EMPENHO, e.NU_EMPENHO, e.VL_EMPENHO,
               (SELECT IFNULL(SUM(VL_SUBTOTAL),0) 
               FROM TJ_CONTROLE_LOCACAO_ITENS
               WHERE ID_EMPENHO = e.ID_EMPENHO) AS VL_DIARIAS,      
               (SELECT IFNULL(SUM(VL_DIFERENCA),0) 
               FROM TJ_CONTROLE_LOCACAO_ITENS
               WHERE ID_EMPENHO = e.ID_EMPENHO) AS VL_DIF,
               (SELECT IFNULL(SUM(VL_TOTALITEM),0) 
               FROM TJ_CONTROLE_LOCACAO_ITENS I
               WHERE ID_EMPENHO = e.ID_EMPENHO) AS VL_UTILIZADO,
               e.VL_EMPENHO - e.VL_ANULADO - 
               (SELECT IFNULL(SUM(VL_TOTALITEM),0) 
               FROM TJ_CONTROLE_LOCACAO_ITENS I
               WHERE ID_EMPENHO = e.ID_EMPENHO) AS VL_SALDO
        FROM TJ_CONTROLE_LOCACAO_EMPENHOS e
        WHERE e.ATIVO = 'S'
        AND e.ID_CL = %s
        """
        cursor.execute(query, (id_cl,))
        empenhos = cursor.fetchall()
        
        # Converter para dicionários
        resultado = []
        for empenho in empenhos:
            resultado.append({
                'ID_EMPENHO': empenho[0],
                'NU_EMPENHO': empenho[1],
                'VL_EMPENHO': float(empenho[2]) if empenho[2] else 0,
                'VL_DIARIAS': float(empenho[3]) if empenho[3] else 0,
                'VL_DIF': float(empenho[4]) if empenho[4] else 0,
                'VL_UTILIZADO': float(empenho[5]) if empenho[5] else 0,
                'VL_SALDO': float(empenho[6]) if empenho[6] else 0
            })
        
        cursor.close()
        return jsonify(resultado)
    except Exception as e:
        app.logger.error(f"Erro ao buscar empenhos: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/saldo_diarias/<int:id_cl>')
@login_required
def api_saldo_diarias(id_cl):
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT V.DE_VEICULO, V.VL_DIARIA_KM, V.QT_DK,  
            (SELECT IFNULL(SUM(QT_DIARIA_KM),0)
                FROM TJ_CONTROLE_LOCACAO_ITENS
                WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC) AS QT_UTILIZADO,
            IFNULL(V.QT_DK - ( SELECT IFNULL(SUM(QT_DIARIA_KM),0)
                        FROM TJ_CONTROLE_LOCACAO_ITENS
                        WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC),0) AS QT_SALDO,
            IFNULL((V.VL_DIARIA_KM * V.QT_DK),0) AS VALOR_TOTAL,
            IFNULL((SELECT CAST(SUM(VL_TOTALITEM) AS DECIMAL(10,2))
                        FROM TJ_CONTROLE_LOCACAO_ITENS
                    WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC
                        AND ID_CL = V.ID_CL),0) AS VL_UTILIZADO,
            IFNULL((V.VL_DIARIA_KM * V.QT_DK) -
                    IFNULL((SELECT SUM(VL_TOTALITEM)
                        FROM TJ_CONTROLE_LOCACAO_ITENS
                    WHERE ID_VEICULO_LOC = V.ID_VEICULO_LOC
                        AND ID_CL = V.ID_CL),0),0) AS VL_SALDO
        FROM TJ_VEICULO_LOCACAO V
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
        SUM(i.VL_TOTALITEM) AS VLTOTAL, i.COMBUSTIVEL
        FROM TJ_CONTROLE_LOCACAO_ITENS i, TJ_MES m
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
                'COMBUSTIVEL': pls[3]
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
        FROM TJ_CONTROLE_LOCACAO_ITENS i
        LEFT JOIN TJ_MOTORISTA m
        ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        TJ_VEICULO_LOCACAO v, TJ_MES x,
        TJ_CONTROLE_LOCACAO_EMPENHOS e
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
        FROM TJ_CONTROLE_LOCACAO_ITENS i, TJ_MES m 
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
        FROM TJ_CONTROLE_LOCACAO_ITENS i 
        LEFT JOIN TJ_MOTORISTA m ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        TJ_VEICULO_LOCACAO v, TJ_MES x, TJ_CONTROLE_LOCACAO_EMPENHOS e 
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
        FROM TJ_CONTROLE_LOCACAO_ITENS i 
        LEFT JOIN TJ_MOTORISTA m ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        TJ_VEICULO_LOCACAO v, TJ_MES x, TJ_CONTROLE_LOCACAO_EMPENHOS e 
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
    return render_template('rel_locacao_analitico.html')

# Rota para listar veículos disponíveis por ID_CL
@app.route('/api/lista_veiculo')
@login_required
def listar_veiculos():
    try:
        id_cl = request.args.get('id_cl')
        if not id_cl:
            return jsonify({'erro': 'ID_CL não fornecido'}), 400
            
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT ID_VEICULO_LOC, DE_VEICULO, VL_DIARIA_KM FROM TJ_VEICULO_LOCACAO WHERE ID_CL = %s", (id_cl,))
        
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
        cursor.execute("SELECT SIGLA_SETOR FROM TJ_SETORES ORDER BY SIGLA_SETOR")
               
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
            FILE_PDF, NOME_ARQUIVO FROM TJ_MOTORISTA
            WHERE ID_MOTORISTA <> 0 ORDER BY NM_MOTORISTA
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
        FROM TJ_CONTROLE_LOCACAO_EMPENHOS
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
    cursor.execute("SELECT MAX(ID_ITEM) FROM TJ_CONTROLE_LOCACAO_ITENS")
    resultado = cursor.fetchone()
    cursor.close()
    
    ultimo_id = resultado[0] if resultado[0] else 0
    return ultimo_id + 1
    

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
        
        # Verificar se o motorista tem CNH cadastrada
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT FILE_PDF, NM_MOTORISTA, NU_TELEFONE, NOME_ARQUIVO FROM TJ_MOTORISTA WHERE ID_MOTORISTA = %s", (id_motorista,))
        motorista_info = cursor.fetchone()
        
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
                    "UPDATE TJ_MOTORISTA SET FILE_PDF = %s, NOME_ARQUIVO = %s WHERE ID_MOTORISTA = %s",
                    (file_content, nome_arquivo_cnh, id_motorista)
                )
                mysql.connection.commit()
                file_pdf = file_content
        
        # Inserir na tabela TJ_CONTROLE_LOCACAO_ITENS
        cursor.execute("""
            INSERT INTO TJ_CONTROLE_LOCACAO_ITENS (
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
        
        # Obter informações do veículo - IMPORTANTE: Também usar dictionary=True aqui
        cursor.execute("SELECT DE_VEICULO FROM TJ_VEICULO_LOCACAO WHERE ID_VEICULO_LOC = %s", (id_veiculo_loc,))
        veiculo_info = cursor.fetchone()
        de_veiculo = veiculo_info['DE_VEICULO']
        
        # Verificar se o motorista tem Email cadastrado
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT EMAIL FROM TJ_MOTORISTA WHERE ID_MOTORISTA = %s", (id_motorista,))
        motorista_email = cursor.fetchone()        
        
        # Enviar e-mail para a empresa locadora
        email_enviado, erro_email = enviar_email_locacao(
            id_item, motorista_info['NM_MOTORISTA'], motorista_info['NU_TELEFONE'],
            dt_inicial, dt_final, hr_inicial, de_veiculo, obs,
            nome_arquivo_cnh, motorista_email, file_pdf  # Passando o conteúdo do PDF
        )
        
        response_data = {
            'sucesso': True,
            'email_enviado': email_enviado,
            'mensagem': 'Locação cadastrada com sucesso!'
        }
        
        if not email_enviado and erro_email:
            response_data['erro_email'] = erro_email
            
        cursor.close()
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Erro ao cadastrar locação: {str(e)}")
        return jsonify({
            'sucesso': False,
            'mensagem': str(e)
        }), 500


def enviar_email_locacao(id_item, nm_motorista, nu_telefone, dt_inicial, dt_final, hr_inicial, de_veiculo, obs, nome_arquivo_cnh, email_mot, file_pdf_content=None):
    try:
        # Obter hora atual para saudação
        hora_atual = datetime.now().hour
        saudacao = "Bom dia" if 5 <= hora_atual < 12 else "Boa tarde" if 12 <= hora_atual < 18 else "Boa noite"
        
        # Obter nome do usuário da sessão
        nome_usuario = session.get('usuario_nome', 'Administrador')
        
        # Formatação do assunto
        assunto = f"TJRO - Locação de Veículo {id_item} - {nm_motorista}"
        
        # Corpo do email para a locadora
        corpo = f'''{saudacao},

Prezados, solicito locação de veículo conforme informações abaixo:

    Período: {dt_inicial} ({hr_inicial}) a {dt_final}
    Veículo: {de_veiculo} ou Similar
    Condutor: {nm_motorista} - Telefone {nu_telefone}

{obs}
    
Segue anexo CNH do condutor.

Atenciosamente,

{nome_usuario}
Tribunal de Justiça do Estado de Rondônia
Seção de Gestão Operacional do Transporte
(69) 3309-6229/6227'''
        
        # Criar mensagem para a locadora
        msg = Message(
            subject=assunto,
            recipients=["Carmem@rovemalocadora.com.br", "atendimentopvh@rovemalocadora.com.br", "atendimento02@rovemalocadora.com.br"],
            body=corpo,
            sender=("TJRO-SEGEOP", "segeop@tjro.jus.br")
        )
        
        # Anexar CNH se disponível
        if file_pdf_content and nome_arquivo_cnh:
            msg.attach(f'CNH_{nome_arquivo_cnh}', 'application/pdf', file_pdf_content)
        
        # Enviar email para a locadora
        mail.send(msg)
        
        # Registrar email no banco de dados
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Formatação da data e hora atual
        data_hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Obter ID_CL com base no ID_ITEM
        cursor.execute("SELECT ID_CL FROM TJ_CONTROLE_LOCACAO_ITENS WHERE ID_ITEM = %s", (id_item,))
        resultado = cursor.fetchone()
        id_cl = resultado['ID_CL'] if resultado else None

        if id_cl:
            # Inserir na tabela de emails (para o email da locadora)
            cursor.execute(
                "INSERT INTO TJ_EMAIL_LOCACAO (ID_ITEM, ID_CL, DESTINATARIO, ASSUNTO, TEXTO, DATA_HORA) VALUES (%s, %s, %s, %s, %s, %s)",
                (id_item, id_cl, "Carmem@rovemalocadora.com.br, atendimentopvh@rovemalocadora.com.br, atendimento02@rovemalocadora.com.br", assunto, corpo, data_hora_atual)
            )
            
            # Atualizar flag de email na tabela de locações
            cursor.execute(
                "UPDATE TJ_CONTROLE_LOCACAO_ITENS SET FL_EMAIL = 'S' WHERE ID_ITEM = %s",
                (id_item,)
            )
            
            mysql.connection.commit()

        # Agora enviar email para o motorista, se tiver email cadastrado
        if email_mot:
            try:
                # Corpo do email para o motorista
                corpo_motorista = f'''{saudacao},

Prezado(a) Usuário(a), foi solicitado locação de veículo conforme informações abaixo:

    Período: {dt_inicial} ({hr_inicial}) a {dt_final}
    Veículo: {de_veiculo} ou Similar
    Condutor: {nm_motorista} - Telefone {nu_telefone}

{obs}

Atenciosamente,

{nome_usuario}
Tribunal de Justiça do Estado de Rondônia
Seção de Gestão Operacional do Transporte
(69) 3309-6229/6227

(Não precisa responder este e-mail)'''

                # Criar mensagem para o motorista - CORREÇÃO AQUI
                msg_motorista = Message(
                    subject=assunto,
                    recipients=[email_mot],  # Removendo as chaves incorretas
                    body=corpo_motorista,
                    sender=("TJRO-SEGEOP", "segeop@tjro.jus.br")
                )
            
                # Enviar email para o motorista
                mail.send(msg_motorista)
                app.logger.info(f"Email enviado para o motorista: {email_mot}")
                
            except Exception as e:
                # Tratar erro específico do email do motorista, mas não interromper a função
                app.logger.error(f"Erro ao enviar email para o motorista: {str(e)}")
                # Não retornar aqui, pois o email para a locadora já foi enviado com sucesso
        
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
            SELECT FILE_PDF, NOME_ARQUIVO FROM TJ_MOTORISTA
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
            FROM TJ_CONTROLE_LOCACAO_ITENS i, TJ_MOTORISTA m
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
            FROM TJ_CONTROLE_LOCACAO_ITENS
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
            SELECT DISTINCT COMBUSTIVEL FROM TJ_CONTROLE_LOCACAO_ITENS
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
            UPDATE TJ_CONTROLE_LOCACAO_ITENS SET
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
            UPDATE TJ_CONTROLE_LOCACAO_ITENS SET
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
            FROM TJ_CONTROLE_LOCACAO_ITENS i, TJ_MOTORISTA m, 
            TJ_CONTROLE_LOCACAO_EMPENHOS e, TJ_VEICULO_LOCACAO v
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


# @app.route('/api/fluxo_lista_setores')
# @login_required
# def fluxo_lista_setores():
#     try:
#         cursor = mysql.connection.cursor()
#         cursor.execute("""
#         SELECT DISTINCT SETOR_SOLICITANTE 
#         FROM TJ_FLUXO_VEICULOS
#         ORDER BY SETOR_SOLICITANTE
#         """)
               
#         items = cursor.fetchall()

#         setores = []
#         for item in items:
#             lista = {'SETOR_SOLICITANTE': item[0]}
#             setores.append(lista)
            
#         cursor.close()
#         return jsonify(setores)
        
#     except Exception as e:
#         app.logger.error(f"Erro ao buscar setores: {str(e)}")
#         return jsonify({"error": str(e)}), 500
    

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
            FROM TJ_FLUXO_VEICULOS
            WHERE SETOR_SOLICITANTE LIKE %s
            ORDER BY SETOR_SOLICITANTE
        """, (f'%{termo}%',))
        
        result = cursor.fetchall()
        cursor.close()
        
        setores = [row[0] for row in result]
        return jsonify(setores)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500    

@app.route('/api/fluxo_lista_destinos')
@login_required
def fluxo_lista_destinos():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
        SELECT DISTINCT DESTINO 
        FROM TJ_FLUXO_VEICULOS
        ORDER BY DESTINO
        """)
               
        items = cursor.fetchall()

        destinos = []
        for item in items:
            lista = {'DESTINO': item[0]}
            destinos.append(lista)
            
        cursor.close()
        return jsonify(destinos)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar setores: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/fluxo_lista_motorista')
@login_required
def fluxo_lista_motorista():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
        SELECT ID_MOTORISTA, NM_MOTORISTA 
        FROM TJ_MOTORISTA WHERE ATIVO = 'S'
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
        cursor = mysql.connection.cursor()
        cursor.execute("""
        SELECT ID_VEICULO, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO 
        FROM TJ_VEICULO WHERE FL_ATENDIMENTO = 'S'
        ORDER BY DS_MODELO
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
                f.NC_CONDUTOR ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA, 
                CONCAT(f.DT_SAIDA,' ',f.HR_SAIDA) AS SAIDA, f.OBS
            FROM TJ_FLUXO_VEICULOS f
            INNER JOIN TJ_VEICULO v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN TJ_MOTORISTA m 
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
                        'id_veiculo': result[4],
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
                f.NC_CONDUTOR ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA, 
                CONCAT(f.DT_SAIDA,' ',f.HR_SAIDA) AS SAIDA, 
                CONCAT(f.DT_RETORNO,' ',f.HR_RETORNO) AS RETORNO, f.OBS_RETORNO
            FROM TJ_FLUXO_VEICULOS f
            INNER JOIN TJ_VEICULO v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN TJ_MOTORISTA m 
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
                f.NC_CONDUTOR ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA, 
                CONCAT(f.DT_SAIDA,' ',f.HR_SAIDA) AS SAIDA, f.OBS
            FROM TJ_FLUXO_VEICULOS f
            INNER JOIN TJ_VEICULO v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN TJ_MOTORISTA m 
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
