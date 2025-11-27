from flask import Flask, render_template, request, make_response, redirect, url_for, flash, jsonify, send_file, session
from flask_mail import Mail, Message
from functools import wraps
import os
from flask_mysqldb import MySQL
import MySQLdb.cursors
import uuid
import base64
from datetime import datetime, timedelta, time
from xhtml2pdf import pisa
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
app.config['MYSQL_CHARSET'] = 'utf8mb4'
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

#@app.route('/logout')
#def logout():
#    session.clear()
#    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    # Se a requisição vier via AJAX, retornar JSON
    if request.headers.get('Content-Type') == 'application/json':
        return jsonify({'success': True})
    return redirect(url_for('login'))


@app.route('/nova_vistoria')
def nova_vistoria():
    # Busca motoristas e veículos do banco de dados
    cur = mysql.connection.cursor()
    cur.execute("SELECT ID_MOTORISTA, NM_MOTORISTA FROM TJ_MOTORISTA WHERE ID_MOTORISTA <> 0 AND ATIVO = 'S' ORDER BY NM_MOTORISTA")
    motoristas = cur.fetchall()
    cur.execute("SELECT ID_VEICULO, CONCAT(DS_MODELO,' - ',NU_PLACA) AS VEICULO FROM TJ_VEICULO WHERE ATIVO = 'S' AND FL_ATENDIMENTO = 'S' ORDER BY DS_MODELO, NU_PLACA")
    veiculos = cur.fetchall()
    cur.close()
    
    return render_template('nova_vistoria.html', motoristas=motoristas, veiculos=veiculos, tipo='SAIDA')

@app.route('/nova_vistoria2')
def nova_vistoria2():
    # Busca motoristas e veículos do banco de dados
    cur = mysql.connection.cursor()
    cur.execute("SELECT ID_MOTORISTA, NM_MOTORISTA FROM TJ_MOTORISTA WHERE ID_MOTORISTA <> 0 AND ATIVO = 'S' ORDER BY NM_MOTORISTA")
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
               v.ASS_USUARIO, v.ASS_MOTORISTA, v.OBS, v.DATA_SAIDA, v.DATA_RETORNO, v.NU_SEI
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
	data_saida=vistoria_saida[6],
	data_retorno=vistoria_saida[7],
	nu_sei=vistoria_saida[8],
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
        data_saida = request.form['dataSaida']
        # Obter data_retorno apenas se estiver presente no formulário
        data_retorno = request.form.get('dataRetorno', None)
        nu_sei = request.form.get('numSei', '')  # Tornando campo SEI opcional
        
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
                   (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, COMBUSTIVEL, HODOMETRO, 
                   ASS_USUARIO, ASS_MOTORISTA, OBS, USUARIO, DATA_SAIDA, NU_SEI) 
                   VALUES (%s, %s, %s, %s, 'EM_TRANSITO', %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_motorista, id_veiculo, data_hora, tipo, combustivel, hodometro, 
                 assinatura_usuario_bin, assinatura_motorista_bin, obs, usuario_nome, data_saida, nu_sei)
            )
        else:  # DEVOLUCAO
            # Para vistorias de DEVOLUCAO, definir status como FINALIZADA
            cur.execute(
                """INSERT INTO VISTORIAS 
                   (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, VISTORIA_SAIDA_ID, COMBUSTIVEL, 
                   HODOMETRO, ASS_USUARIO, ASS_MOTORISTA, OBS, USUARIO, DATA_SAIDA, DATA_RETORNO, NU_SEI) 
                   VALUES (%s, %s, %s, %s, 'FINALIZADA', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_motorista, id_veiculo, data_hora, tipo, vistoria_saida_id, combustivel, hodometro, 
                 assinatura_usuario_bin, assinatura_motorista_bin, obs, usuario_nome, data_saida, data_retorno, nu_sei)
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
                   v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL, ve.DS_MODELO, v.VISTORIA_SAIDA_ID, v.ASS_USUARIO, 
		   v.ASS_MOTORISTA, v.HODOMETRO, v.OBS, v.USUARIO, v.DATA_SAIDA, v.DATA_RETORNO, v.NU_SEI
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
                ID_MOTORISTA, CAD_MOTORISTA,
                CASE WHEN ATIVO='S' THEN NM_MOTORISTA 
                ELSE CONCAT(NM_MOTORISTA,' (INATIVO)') END AS MOTORISTA,
                ORDEM_LISTA AS TIPO_CADASTRO, SIGLA_SETOR,
                FILE_PDF IS NOT NULL AS FILE_PDF, ATIVO,
                DATE_FORMAT(DT_INICIO, '%d/%m/%Y') AS DT_INICIO,
                DATE_FORMAT(DT_FIM, '%d/%m/%Y') AS DT_FIM
            FROM TJ_MOTORISTA 
            WHERE ID_MOTORISTA > 0
            AND CONCAT(CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, SIGLA_SETOR) LIKE %s 
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query, (f'%{nome}%',))
        else:
            query = """
            SELECT 
                ID_MOTORISTA, CAD_MOTORISTA, 
                CASE WHEN ATIVO='S' THEN NM_MOTORISTA 
                ELSE CONCAT(NM_MOTORISTA,' (INATIVO)') END AS MOTORISTA, 
                ORDEM_LISTA AS TIPO_CADASTRO, SIGLA_SETOR,
                FILE_PDF IS NOT NULL AS FILE_PDF, ATIVO,
                DATE_FORMAT(DT_INICIO, '%d/%m/%Y') AS DT_INICIO,
                DATE_FORMAT(DT_FIM, '%d/%m/%Y') AS DT_FIM
            FROM TJ_MOTORISTA
            WHERE ID_MOTORISTA > 0
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query)
        
        columns = ['id_motorista', 'cad_motorista', 'nm_motorista', 'tipo_cadastro', 'sigla_setor', 'file_pdf', 'ativo', 'dt_inicio', 'dt_fim']
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
            NU_TELEFONE, OBS_MOTORISTA, ATIVO, NOME_ARQUIVO, EMAIL,
            DT_INICIO, DT_FIM
        FROM TJ_MOTORISTA 
        WHERE ID_MOTORISTA = %s
        """
        cursor.execute(query, (id_motorista,))
        result = cursor.fetchone()
        cursor.close()
        
        if result:
            # Formatar datas manualmente em Python
            dt_inicio_formatada = None
            dt_fim_formatada = None
            
            if result[13]:  # DT_INICIO
                if isinstance(result[13], str):
                    dt_inicio_formatada = result[13]
                else:
                    dt_inicio_formatada = result[13].strftime('%d/%m/%Y')
            
            if result[14]:  # DT_FIM
                if isinstance(result[14], str):
                    dt_fim_formatada = result[14]
                else:
                    dt_fim_formatada = result[14].strftime('%d/%m/%Y')
            
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
                'dt_inicio': dt_inicio_formatada,
                'dt_fim': dt_fim_formatada
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
        4: 'Cadastro de Condutores',
        5: 'Tercerizado'    
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
        dt_inicio = request.form.get('dt_inicio')
        dt_fim = request.form.get('dt_fim', None)
        
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
        INSERT INTO TJ_MOTORISTA (
            ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, 
            SIGLA_SETOR, CAT_CNH, DT_VALIDADE_CNH, ULTIMA_ATUALIZACAO, 
            NU_TELEFONE, OBS_MOTORISTA, ATIVO, USUARIO, DT_TRANSACAO, 
            FILE_PDF, NOME_ARQUIVO, ORDEM_LISTA, EMAIL, DT_INICIO, DT_FIM
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'S', %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            novo_id, cad_motorista, nm_motorista, tipo_cadastro_desc, 
            sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
            nu_telefone, obs_motorista, session.get('usuario_id'), 
            dt_transacao, file_blob, nome_arquivo, tipo_cadastro, email,
            dt_inicio_db, dt_fim_db
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
        4: 'Cadastro de Condutores',
        5: 'Tercerizado'
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
        dt_inicio = request.form.get('dt_inicio')
        dt_fim = request.form.get('dt_fim', None)
        
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
        if file_pdf:
            # Update with file
            query = """
            UPDATE TJ_MOTORISTA 
            SET CAD_MOTORISTA = %s, NM_MOTORISTA = %s, TIPO_CADASTRO = %s, 
                SIGLA_SETOR = %s, CAT_CNH = %s, DT_VALIDADE_CNH = %s, 
                ULTIMA_ATUALIZACAO = %s, NU_TELEFONE = %s, OBS_MOTORISTA = %s, 
                ATIVO = %s, USUARIO = %s, 
                FILE_PDF = %s, NOME_ARQUIVO = %s, ORDEM_LISTA = %s, EMAIL = %s,
                DT_INICIO = %s, DT_FIM = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                file_blob, nome_arquivo, tipo_cadastro, email,
                dt_inicio_db, dt_fim_db, id_motorista
            ))
        else:
            # Update without changing file
            query = """
            UPDATE TJ_MOTORISTA 
            SET CAD_MOTORISTA = %s, NM_MOTORISTA = %s, TIPO_CADASTRO = %s, 
                SIGLA_SETOR = %s, CAT_CNH = %s, DT_VALIDADE_CNH = %s, 
                ULTIMA_ATUALIZACAO = %s, NU_TELEFONE = %s, OBS_MOTORISTA = %s, 
                ATIVO = %s, USUARIO = %s, ORDEM_LISTA = %s, EMAIL = %s,
                DT_INICIO = %s, DT_FIM = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                tipo_cadastro, email, dt_inicio_db, dt_fim_db, id_motorista
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
        query = "SELECT FILE_PDF, NOME_ARQUIVO FROM TJ_MOTORISTA WHERE ID_MOTORISTA = %s"
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

@app.route('/controle_locacoes')
@login_required
def controle_locacoes():
    return render_template('controle_locacoes.html')

@app.route('/api/tipos_locacao')
@login_required
def api_tipos_locacao():
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT ID_TIPO_LOCACAO, DE_TIPO_LOCACAO
        FROM TJ_TIPO_LOCACAO
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
        FROM TJ_CONTROLE_LOCACAO cl
        INNER JOIN TJ_FORNECEDOR f ON f.ID_FORNECEDOR = cl.ID_FORNECEDOR
        INNER JOIN TJ_TIPO_LOCACAO tl ON tl.ID_TIPO_LOCACAO = cl.ID_TIPO_LOCACAO
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
            TJ_CONTROLE_LOCACAO_EMPENHOS e
        LEFT JOIN (
            SELECT
                i.ID_EMPENHO,
                SUM(i.VL_TOTALITEM) AS VL_TOTAL
            FROM TJ_CONTROLE_LOCACAO_ITENS i
            GROUP BY i.ID_EMPENHO
        ) st ON e.ID_EMPENHO = st.ID_EMPENHO
        LEFT JOIN (
            SELECT
                i.ID_EMPENHO,
                SUM(i.VL_TOTALITEM) AS VL_LIQUIDADO
            FROM TJ_CONTROLE_LOCACAO_ITENS i
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
                    FROM TJ_CONTROLE_LOCACAO_ITENS
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
            CONCAT((SELECT DE_MES FROM TJ_MES WHERE ID_MES = i.ID_MES),'/',i.ID_EXERCICIO) AS MESANO,
            SUM(i.VL_SUBTOTAL) AS SUBTOTAL, 
            SUM(i.VL_DIFERENCA) AS HORA_EXTRA, 
            SUM(i.VL_TOTALITEM) AS TOTAL,
            SUM(i.KM_RODADO) AS TOTAL_KM
        FROM TJ_CONTROLE_LOCACAO_ITENS i
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
        SUM(i.VL_TOTALITEM) AS VLTOTAL, i.COMBUSTIVEL,
	SUM(i.KM_RODADO) AS KM 
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
        
# @app.route('/rel_locacao_analitico')
# @login_required
# def rel_locacao_analitico():
#     return render_template('rel_locacao_analitico.html')

@app.route('/rel_locacao_analitico')
@login_required
def rel_locacao_analitico_page():
    """Gera o relatório analítico como PDF"""
    try:
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
        FROM TJ_CONTROLE_LOCACAO_ITENS i 
        LEFT JOIN TJ_MOTORISTA m ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
        TJ_VEICULO_LOCACAO v, TJ_MES x, TJ_CONTROLE_LOCACAO_EMPENHOS e 
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
            FROM TJ_CONTROLE_LOCACAO cl
            JOIN TJ_FORNECEDOR f ON f.ID_FORNECEDOR = cl.ID_FORNECEDOR
            WHERE cl.ID_CL = %s
        """, (id_cl,))
        processo_info = cursor.fetchone()
        
        cursor.close()
        
        # Converter logo para base64
        import os
        import base64
        logo_path = os.path.join(app.root_path, 'static', 'img', 'logo.png')
        logo_base64 = ""
        
        try:
            with open(logo_path, 'rb') as f:
                logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            app.logger.warning(f"Não foi possível carregar a logo: {str(e)}")
        
        # Renderizar o HTML primeiro
        html_content = render_template('rel_locacao_analitico.html', 
                                      items=items, 
                                      processo_info=processo_info,
                                      mes_ano_filtro=mes_ano,
                                      logo_base64=logo_base64)
        
        # Converter para PDF com xhtml2pdf
        pdf_buffer = BytesIO()
        pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)
        
        if pisa_status.err:
            return "Erro ao gerar PDF", 500
            
        pdf_buffer.seek(0)
        
        response = make_response(pdf_buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=relatorio_locacoes_{id_cl}.pdf'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Erro ao gerar relatório: {str(e)}")
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
            FROM TJ_VEICULO_LOCACAO
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
            FROM TJ_CONTROLE_LOCACAO_EMPENHOS
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
            FROM TJ_MOTORISTA 
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
    Verifica se o tipo de veículo tem vínculo com fornecedor (sem TJ_VEICULO_LOCACAO)
    Busca item do fornecedor baseado no ID_TIPOVEICULO
    """
    cursor = None
    try:
        id_tipoveiculo = request.args.get('id_tipoveiculo')
        
        if not id_tipoveiculo:
            return jsonify({'tem_vinculo': False}), 400
        
        cursor = mysql.connection.cursor()
        
        # Verificar se tem vínculo com TJ_VEICULO_LOCACAO (se tiver, não entra na nova regra)
        cursor.execute("""
            SELECT COUNT(*) 
            FROM TJ_VEICULO_LOCACAO 
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
            INNER JOIN TJ_FORNECEDOR f ON f.ID_FORNECEDOR = tv.ID_FORNECEDOR
            LEFT JOIN TJ_FORNECEDOR_ITEM fi ON fi.ID_FORNECEDOR = tv.ID_FORNECEDOR 
                                             AND fi.ID_TIPOVEICULO = tv.ID_TIPOVEICULO
            LEFT JOIN TJ_CONTROLE_LOCACAO cl ON cl.ID_FORNECEDOR = tv.ID_FORNECEDOR 
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
            FROM TJ_CONTROLE_LOCACAO_ITENS
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
        cursor.execute("SELECT FILE_PDF, NM_MOTORISTA, NU_TELEFONE, NOME_ARQUIVO, EMAIL FROM TJ_MOTORISTA WHERE ID_MOTORISTA = %s", (id_motorista,))
        motorista_info = cursor.fetchone()
        
        # Buscar o email do fornecedor
        cursor.execute("SELECT EMAIL FROM TJ_FORNECEDOR f INNER JOIN TJ_CONTROLE_LOCACAO cl ON f.ID_FORNECEDOR = cl.ID_FORNECEDOR WHERE cl.ID_CL = %s", (id_cl,))
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
        
        # Obter informações do veículo
        cursor.execute("SELECT DE_VEICULO FROM TJ_VEICULO_LOCACAO WHERE ID_VEICULO_LOC = %s", (id_veiculo_loc,))
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
            "INSERT INTO TJ_EMAIL_LOCACAO (ID_ITEM, ID_CL, DESTINATARIO, ASSUNTO, TEXTO, DATA_HORA) VALUES (%s, %s, %s, %s, %s, %s)",
            (id_item, id_cl, emails_string, assunto, corpo_texto, data_hora_atual)
        )
        
        # Atualizar flag de email na tabela de locações
        cursor.execute(
            "UPDATE TJ_CONTROLE_LOCACAO_ITENS SET FL_EMAIL = 'S' WHERE ID_ITEM = %s",
            (id_item,)
        )
        
        mysql.connection.commit()
        cursor.close()
        
        return True, None
    
    except Exception as e:
        app.logger.error(f"Erro ao enviar email: {str(e)}")
        return False, str(e)
		

# def enviar_email_locacao(id_item, nu_sei, nm_motorista, nu_telefone, dt_inicial, dt_final, hr_inicial, de_veiculo, obs, nome_arquivo_cnh, email_mot, file_pdf_content=None):
#     try:
#         # Obter hora atual para saudação
#         hora_atual = datetime.now().hour
#         saudacao = "Bom dia" if 5 <= hora_atual < 12 else "Boa tarde" if 12 <= hora_atual < 18 else "Boa noite"
        
#         # Obter nome do usuário da sessão
#         nome_usuario = session.get('usuario_nome', 'Administrador')
        
#         # Formatação do assunto
#         assunto = f"TJRO - Locação de Veículo {id_item} - {nm_motorista}"
        
#         # Corpo do email para a locadora
#         corpo = f'''{saudacao},
# Prezados, solicito locação de veículo conforme informações abaixo:
#     Período: {dt_inicial} ({hr_inicial}) a {dt_final}
#     Veículo: {de_veiculo} ou Similar
#     Condutor: {nm_motorista} - Telefone {nu_telefone}
# {obs}
    
# Segue anexo CNH do condutor.
# Atenciosamente,
# {nome_usuario}
# Tribunal de Justiça do Estado de Rondônia
# Seção de Gestão Operacional do Transporte
# (69) 3309-6229/6227'''
        
#         # Criar mensagem para a locadora
#         msg = Message(
#             subject=assunto,
#             recipients=["Carmem@rovemalocadora.com.br", "atendimentopvh@rovemalocadora.com.br", "atendimento02@rovemalocadora.com.br"],
#             body=corpo,
#             sender=("TJRO-SEGEOP", "segeop@tjro.jus.br")
#         )
        
#         # Anexar CNH se disponível
#         if file_pdf_content and nome_arquivo_cnh:
#             msg.attach(f'CNH_{nome_arquivo_cnh}', 'application/pdf', file_pdf_content)
        
#         # Enviar email para a locadora
#         mail.send(msg)
        
#         # Registrar email no banco de dados
#         cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
#         # Formatação da data e hora atual
#         data_hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
#         # Obter ID_CL com base no ID_ITEM
#         cursor.execute("SELECT ID_CL FROM TJ_CONTROLE_LOCACAO_ITENS WHERE ID_ITEM = %s", (id_item,))
#         resultado = cursor.fetchone()
#         id_cl = resultado['ID_CL'] if resultado else None
#         if id_cl:
#             # Inserir na tabela de emails (para o email da locadora)
#             cursor.execute(
#                 "INSERT INTO TJ_EMAIL_LOCACAO (ID_ITEM, ID_CL, DESTINATARIO, ASSUNTO, TEXTO, DATA_HORA) VALUES (%s, %s, %s, %s, %s, %s)",
#                 (id_item, id_cl, "Carmem@rovemalocadora.com.br, atendimentopvh@rovemalocadora.com.br, atendimento02@rovemalocadora.com.br", assunto, corpo, data_hora_atual)
#             )
            
#             # Atualizar flag de email na tabela de locações
#             cursor.execute(
#                 "UPDATE TJ_CONTROLE_LOCACAO_ITENS SET FL_EMAIL = 'S' WHERE ID_ITEM = %s",
#                 (id_item,)
#             )
            
#             mysql.connection.commit()
#         # Agora enviar email para o motorista, se tiver email cadastrado
#         if email_mot:
#             try:
#                 # Corpo do email para o motorista
#                 corpo_motorista = f'''{saudacao},
# Prezado(a) Usuário(a), foi solicitado locação de veículo conforme informações abaixo:
#     Período: {dt_inicial} ({hr_inicial}) a {dt_final}
#     Veículo: {de_veiculo} ou Similar
#     Condutor: {nm_motorista} - Telefone {nu_telefone}
# {obs}
# Atenciosamente,
# {nome_usuario}
# Tribunal de Justiça do Estado de Rondônia
# Seção de Gestão Operacional do Transporte
# (69) 3309-6229/6227
# (Não precisa responder este e-mail)'''
#                 # Criar mensagem para o motorista - CORREÇÃO AQUI
#                 msg_motorista = Message(
#                     subject=assunto,
#                     recipients=[email_mot],  # Removendo as chaves incorretas
#                     body=corpo_motorista,
#                     sender=("TJRO-SEGEOP", "segeop@tjro.jus.br")
#                 )
            
#                 # Enviar email para o motorista
#                 mail.send(msg_motorista)
#                 app.logger.info(f"Email enviado para o motorista: {email_mot}")
                
#             except Exception as e:
#                 # Tratar erro específico do email do motorista, mas não interromper a função
#                 app.logger.error(f"Erro ao enviar email para o motorista: {str(e)}")
#                 # Não retornar aqui, pois o email para a locadora já foi enviado com sucesso
        
#         cursor.close()
#         return True, None
    
#     except Exception as e:
#         app.logger.error(f"Erro ao enviar email: {str(e)}")
#         return False, str(e)

        
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
    
@app.route('/api/excluir_locacao/<int:iditem>', methods=['DELETE'])
@login_required
def excluir_locacao(iditem):
    try:
        # Verificar se o item existe antes de excluir
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT ID_ITEM FROM TJ_CONTROLE_LOCACAO_ITENS WHERE ID_ITEM = %s", (iditem,))
        item = cursor.fetchone()
        
        if not item:
            return jsonify({
                'sucesso': False,
                'mensagem': 'Item não encontrado'
            }), 404
        
        # Exclui os emails relacionados
        cursor.execute("""
            DELETE FROM TJ_EMAIL_LOCACAO
            WHERE ID_ITEM = %s
        """, (iditem,))
        
        # Exclui a locação
        cursor.execute("""
            DELETE FROM TJ_CONTROLE_LOCACAO_ITENS
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
            FROM TJ_FLUXO_VEICULOS
            WHERE DESTINO LIKE %s
            ORDER BY DESTINO
        """, (f'%{termo}%',))
        
        result = cursor.fetchall()
        cursor.close()
        
        destinos = [row[0] for row in result]
        return jsonify(destinos)
    except Exception as e:
        return jsonify({'erro': str(e)}), 500    
        
# @app.route('/api/fluxo_lista_destinos')
# @login_required
# def fluxo_lista_destinos():
#     try:
#         cursor = mysql.connection.cursor()
#         cursor.execute("""
#         SELECT DISTINCT DESTINO 
#         FROM TJ_FLUXO_VEICULOS
#         ORDER BY DESTINO
#         """)
               
#         items = cursor.fetchall()
#         destinos = []
#         for item in items:
#             lista = {'DESTINO': item[0]}
#             destinos.append(lista)
            
#         cursor.close()
#         return jsonify(destinos)
        
#     except Exception as e:
#         app.logger.error(f"Erro ao buscar setores: {str(e)}")
#         return jsonify({"error": str(e)}), 500

@app.route('/api/fluxo_lista_motorista')
@login_required
def fluxo_lista_motorista():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
        SELECT ID_MOTORISTA, NM_MOTORISTA 
        FROM TJ_MOTORISTA WHERE ATIVO = 'S' AND ID_MOTORISTA <> 0
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
        # FROM TJ_VEICULO WHERE FL_ATENDIMENTO = 'S'
        # ORDER BY DS_MODELO
  
        cursor = mysql.connection.cursor()
        cursor.execute("""
        SELECT v.ID_VEICULO, CONCAT(v.DS_MODELO,' - ',v.NU_PLACA) AS VEICULO 
        FROM TJ_VEICULO v 
        WHERE v.ID_VEICULO NOT IN 
            (SELECT ID_VEICULO FROM TJ_FLUXO_VEICULOS
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
                CONCAT('*',f.NC_CONDUTOR) ELSE COALESCE(m.NM_MOTORISTA, '')  END AS MOTORISTA, 
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
            FROM TJ_FLUXO_VEICULOS f
            INNER JOIN TJ_VEICULO v 
                ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN TJ_MOTORISTA m 
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
    cursor.execute("SELECT MAX(ID_FLUXO) FROM TJ_FLUXO_VEICULOS")
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
        # Inserir na tabela TJ_FLUXO_VEICULOS
        cursor.execute("""
            INSERT INTO TJ_FLUXO_VEICULOS (
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
        # Inserir na tabela TJ_FLUXO_VEICULOS
        cursor.execute("""
            UPDATE TJ_FLUXO_VEICULOS SET
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
            FROM TJ_MOTORISTA 
            WHERE ID_MOTORISTA > 0 AND ATIVO = 'S'
            AND CONCAT(CAD_MOTORISTA, NM_MOTORISTA, TIPO_CADASTRO, SIGLA_SETOR) LIKE %s 
            ORDER BY NM_MOTORISTA
            """
            cursor.execute(query, (f'%{nome}%',))
        else:
            query = """
            SELECT ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, SIGLA_SETOR
            FROM TJ_MOTORISTA
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
def veiculos_frota():
    return render_template('veiculos_frota.html')
	
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
            FROM TJ_VEICULO v
            LEFT JOIN TJ_CATEGORIA_VEICULO c ON v.ID_CATEGORIA = c.ID_CAT_VEICULO
            WHERE v.NU_PLACA LIKE %s OR v.DS_MODELO LIKE %s OR v.MARCA LIKE %s
            ORDER BY v.ID_VEICULO DESC
            """
            cursor.execute(query, (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'))
        else:
            # Busca todos
            query = """
            SELECT v.*, c.DS_CAT_VEICULO 
            FROM TJ_VEICULO v
            LEFT JOIN TJ_CATEGORIA_VEICULO c ON v.ID_CATEGORIA = c.ID_CAT_VEICULO
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
        FROM TJ_VEICULO v
        LEFT JOIN TJ_CATEGORIA_VEICULO c ON v.ID_CATEGORIA = c.ID_CAT_VEICULO
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
        cursor.execute("SELECT COALESCE(MAX(ID_VEICULO), 0) + 1 FROM TJ_VEICULO")
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
        INSERT INTO TJ_VEICULO (
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
        UPDATE TJ_VEICULO SET
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
        
        cursor.execute("SELECT * FROM TJ_CATEGORIA_VEICULO ORDER BY DS_CAT_VEICULO")
        
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
            FROM TJ_VEICULO v
            INNER JOIN TJ_FLUXO_VEICULOS f ON v.ID_VEICULO = f.ID_VEICULO
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
            FROM TJ_MOTORISTA m
            INNER JOIN TJ_FLUXO_VEICULOS f ON m.ID_MOTORISTA = f.ID_MOTORISTA
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
            FROM TJ_FLUXO_VEICULOS f
            INNER JOIN TJ_VEICULO v ON v.ID_VEICULO = f.ID_VEICULO
            LEFT JOIN TJ_MOTORISTA m ON f.ID_MOTORISTA = m.ID_MOTORISTA AND f.ID_MOTORISTA > 0
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
    Cria registro na TJ_CONTROLE_LOCACAO_ITENS para locações com fornecedor
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
            FROM ATENDIMENTO_DEMANDAS ad
            JOIN TIPO_VEICULO tv ON tv.ID_TIPOVEICULO = ad.ID_TIPOVEICULO
            LEFT JOIN TJ_CONTROLE_LOCACAO cl ON cl.ID_FORNECEDOR = tv.ID_FORNECEDOR
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
            INSERT INTO TJ_CONTROLE_LOCACAO_ITENS 
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
            FROM ATENDIMENTO_DEMANDAS
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

# API: Buscar dados da agenda por semana (CORRIGIDA - VERSÃO FINAL)
@app.route('/api/agenda/dados', methods=['GET'])
@login_required
def buscar_dados_agenda():
    cursor = None
    try:
        inicio = request.args.get('inicio')
        fim = request.args.get('fim')

        cursor = mysql.connection.cursor()

        # 1. Lista de Motoristas SEGEOP
        cursor.execute("""
            SELECT ID_MOTORISTA, NM_MOTORISTA, CAD_MOTORISTA, NU_TELEFONE, TIPO_CADASTRO
            FROM TJ_MOTORISTA
            WHERE TIPO_CADASTRO IN ('Motorista Atendimento','Tercerizado')
              AND ATIVO = 'S'
            ORDER BY ORDEM_LISTA, NM_MOTORISTA
        """)
        motoristas = []
        for r in cursor.fetchall():
            motoristas.append({
                'id': r[0], 
                'nome': r[1], 
                'cad': r[2] if len(r) > 2 else '', 
                'telefone': r[3] if len(r) > 3 else '', 
                'tipo': r[4] if len(r) > 4 else ''
            })

        # 1.1 TODOS os Motoristas Ativos (para select na edição/outros)
        cursor.execute("""
            SELECT ID_MOTORISTA, NM_MOTORISTA, CAD_MOTORISTA, NU_TELEFONE, TIPO_CADASTRO
            FROM TJ_MOTORISTA
            WHERE ATIVO = 'S'
            ORDER BY NM_MOTORISTA
        """)
        todos_motoristas = []
        for r in cursor.fetchall():
            todos_motoristas.append({
                'id': r[0], 
                'nome': r[1], 
                'cad': r[2] if len(r) > 2 else '', 
                'telefone': r[3] if len(r) > 3 else '', 
                'tipo': r[4] if len(r) > 4 else ''
            })

        # 1.2 Outros Motoristas (NÃO SEGEOP) com demandas no período + Não Cadastrados
        query_outros = """
            SELECT DISTINCT m.ID_MOTORISTA, m.NM_MOTORISTA, m.CAD_MOTORISTA, 
                   m.NU_TELEFONE, m.TIPO_CADASTRO
            FROM TJ_MOTORISTA m
            INNER JOIN ATENDIMENTO_DEMANDAS ae ON ae.ID_MOTORISTA = m.ID_MOTORISTA
            WHERE m.TIPO_CADASTRO NOT IN ('Motorista Atendimento','Tercerizado')
              AND m.ATIVO = 'S'
              AND ae.DT_INICIO <= %s 
              AND ae.DT_FIM >= %s
            UNION 
            SELECT DISTINCT 0 as ID_MOTORISTA, 
                   CONCAT(NC_MOTORISTA, ' (Não Cadastrado)') as NM_MOTORISTA, 
                   '' AS CAD_MOTORISTA, 
                   '' AS NU_TELEFONE, 
                   'Não Cadastrado' as TIPO_CADASTRO
            FROM ATENDIMENTO_DEMANDAS
            WHERE DT_INICIO <= %s 
              AND DT_FIM >= %s
              AND ID_MOTORISTA = 0
              AND NC_MOTORISTA IS NOT NULL
              AND NC_MOTORISTA != ''
            ORDER BY NM_MOTORISTA
        """
        
        cursor.execute(query_outros, (fim, inicio, fim, inicio))
        
        outros_motoristas = []
        for r in cursor.fetchall():
            outros_motoristas.append({
                'id': r[0], 
                'nome': r[1], 
                'cad': r[2] if len(r) > 2 else '', 
                'telefone': r[3] if len(r) > 3 else '', 
                'tipo': r[4] if len(r) > 4 else ''
            })

        # 2. Demandas dos Motoristas
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
            FROM ATENDIMENTO_DEMANDAS ae
            LEFT JOIN TJ_MOTORISTA m ON m.ID_MOTORISTA = ae.ID_MOTORISTA
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
                'nc_motorista': r[20] or ''
            })

        # 3. Lista de Veículos PADRÃO (COM VALIDAÇÃO DE PERÍODO)
        cursor.execute("""
            SELECT ID_VEICULO, DS_MODELO, NU_PLACA
            FROM TJ_VEICULO 
            WHERE FL_ATENDIMENTO = 'S' 
              AND ATIVO = 'S'
              AND (DT_INICIO IS NULL OR DT_INICIO <= %s)
              AND (DT_FIM IS NULL OR DT_FIM >= %s)
            ORDER BY ORIGEM_VEICULO DESC, DS_MODELO
        """, (fim, inicio))
        veiculos = []
        for r in cursor.fetchall():
            veiculos.append({
                'id': r[0], 
                'veiculo': f"{r[1]} - {r[2]}", 
                'modelo': r[1], 
                'placa': r[2]
            })

        # 4. Veículos EXTRAS (COM VALIDAÇÃO DE PERÍODO)
        cursor.execute("""
            SELECT DISTINCT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
            FROM TJ_VEICULO v
            INNER JOIN ATENDIMENTO_DEMANDAS ad ON ad.ID_VEICULO = v.ID_VEICULO
            WHERE v.FL_ATENDIMENTO = 'N' 
              AND v.ATIVO = 'S'
              AND ad.DT_INICIO <= %s 
              AND ad.DT_FIM >= %s
              AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
              AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
            ORDER BY v.DS_MODELO, v.NU_PLACA
        """, (fim, inicio, fim, inicio))
        
        veiculos_extras = []
        for r in cursor.fetchall():
            veiculos_extras.append({
                'id': r[0],
                'veiculo': f"{r[1]} - {r[2]}",
                'modelo': r[1],
                'placa': r[2]
            })

        return jsonify({
            'motoristas': motoristas,
            'outros_motoristas': outros_motoristas,
            'todos_motoristas': todos_motoristas,
            'demandas': demandas,
            'veiculos': veiculos,
            'veiculos_extras': veiculos_extras
        })

    except Exception as e:
        print(f"Erro em buscar_dados_agenda: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e), 
            'motoristas': [],
            'outros_motoristas': [],
            'todos_motoristas': [],
            'demandas': [], 
            'veiculos': [],
            'veiculos_extras': []
        }), 500
    finally:
        if cursor:
            cursor.close()
			
			
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
                    FROM TJ_VEICULO v
                    WHERE v.FL_ATENDIMENTO = 'S' 
                      AND v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                    ORDER BY v.DS_MODELO
                """, (dt_fim, dt_inicio))
            else:
                cursor.execute("""
                    SELECT v.ID_VEICULO, v.DS_MODELO, v.NU_PLACA
                    FROM TJ_VEICULO v
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
                    FROM TJ_VEICULO v
                    WHERE v.FL_ATENDIMENTO = 'S' 
                      AND v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ATENDIMENTO_DEMANDAS ad
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
                    FROM TJ_VEICULO v
                    WHERE v.FL_ATENDIMENTO = 'S' 
                      AND v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ATENDIMENTO_DEMANDAS ad
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


# API: Criar nova demanda (MODIFICADA)
@app.route('/api/agenda/demanda', methods=['POST'])
@login_required
def criar_demanda():
    try:
        data = request.get_json()
        cursor = mysql.connection.cursor()

		# Obter ID do usuário da sessão
        usuario = session.get('usuario_login')		
        
        # Converter horário para formato TIME ou NULL
        horario = data.get('horario')
        if horario and horario.strip():
            horario_value = horario + ':00'
        else:
            horario_value = None
        
        cursor.execute("""
            INSERT INTO ATENDIMENTO_DEMANDAS 
            (ID_MOTORISTA, ID_TIPOVEICULO, ID_VEICULO, ID_TIPODEMANDA, 
             DT_INICIO, DT_FIM, SETOR, SOLICITANTE, DESTINO, NU_SEI, 
             OBS, SOLICITADO, HORARIO, TODOS_VEICULOS, NC_MOTORISTA, DT_LANCAMENTO, USUARIO)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
        """, (
            data.get('id_motorista'), 
            data.get('id_tipoveiculo'), 
            data.get('id_veiculo'),
            data['id_tipodemanda'], 
            data['dt_inicio'], 
            data['dt_fim'],
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
        cursor.close()
        
        return jsonify({'success': True, 'id': id_ad})
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao criar demanda: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# API: Atualizar demanda (MODIFICADA)
@app.route('/api/agenda/demanda/<int:id_ad>', methods=['PUT'])
@login_required
def atualizar_demanda(id_ad):
    try:
        data = request.get_json()
        cursor = mysql.connection.cursor()

		# Obter ID do usuário da sessão
        usuario = session.get('usuario_login')
        
        # Converter horário para formato TIME ou NULL
        horario = data.get('horario')
        if horario and horario.strip():
            horario_value = horario + ':00'
        else:
            horario_value = None
        
        cursor.execute("""
            UPDATE ATENDIMENTO_DEMANDAS 
            SET ID_MOTORISTA = %s, ID_TIPOVEICULO = %s, ID_VEICULO = %s,
                ID_TIPODEMANDA = %s, DT_INICIO = %s, DT_FIM = %s,
                SETOR = %s, SOLICITANTE = %s, DESTINO = %s, NU_SEI = %s,
                OBS = %s, SOLICITADO = %s, HORARIO = %s, TODOS_VEICULOS = %s, 
                NC_MOTORISTA = %s, USUARIO = %s
            WHERE ID_AD = %s
        """, (
            data.get('id_motorista'), 
            data.get('id_tipoveiculo'), 
            data.get('id_veiculo'),
            data['id_tipodemanda'], 
            data['dt_inicio'], 
            data['dt_fim'],
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
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True})
    except Exception as e:
        mysql.connection.rollback()
        print(f"Erro ao atualizar demanda: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
		
# API: Excluir demanda
@app.route('/api/agenda/demanda/<int:id_ad>', methods=['DELETE'])
@login_required
def excluir_demanda(id_ad):
    try:
        cursor = mysql.connection.cursor()
        
        # Primeiro deleta as tabelas dependentes (com FK)
        cursor.execute("DELETE FROM EMAIL_OUTRAS_LOCACOES WHERE ID_AD = %s", (id_ad,))
        cursor.execute("DELETE FROM TJ_CONTROLE_LOCACAO_ITENS WHERE ID_AD = %s", (id_ad,))
        
        # Por último deleta a tabela principal
        cursor.execute("DELETE FROM ATENDIMENTO_DEMANDAS WHERE ID_AD = %s", (id_ad,))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500

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
                ORDEM_EXIBICAO,
                ATIVO
            FROM TIPO_DEMANDA
            WHERE ATIVO = 'S'
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
                'ordem_exibicao': r[18] or 999,
                'ativo': r[19] == 'S'
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
            SELECT ID_ITEM, ID_MOTORISTA, DS_VEICULO_MOD, DATA_INICIO, DATA_FIM, FL_STATUS
            FROM TJ_CONTROLE_LOCACAO_ITENS
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
                'fl_status': r[5] or ''
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
                FROM ATENDIMENTO_DEMANDAS
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
                FROM ATENDIMENTO_DEMANDAS
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
                FROM TJ_VEICULO v
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
                    FROM TJ_VEICULO v
                    WHERE v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ATENDIMENTO_DEMANDAS ad
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
                    FROM TJ_VEICULO v
                    WHERE v.ATIVO = 'S'
                      AND (v.DT_INICIO IS NULL OR v.DT_INICIO <= %s)
                      AND (v.DT_FIM IS NULL OR v.DT_FIM >= %s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ATENDIMENTO_DEMANDAS ad
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
            FROM TJ_SETORES
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


@app.route('/api/criar_locacao_fornecedor', methods=['POST'])
@login_required
def criar_locacao_fornecedor():
    """
    Cria registro na TJ_CONTROLE_LOCACAO_ITENS para locação com fornecedor
    """
    try:
        data = request.get_json()
        id_demanda = data.get('id_demanda')
        
        if not id_demanda:
            return jsonify({'erro': 'ID da demanda não informado'}), 400
        
        id_item = criar_registro_locacao_fornecedor(id_demanda)
        
        if id_item:
            return jsonify({
                'success': True,
                'id_item': id_item,
                'mensagem': 'Registro de locação criado com sucesso'
            })
        else:
            return jsonify({
                'erro': 'Erro ao criar registro de locação'
            }), 500
            
    except Exception as e:
        app.logger.error(f"Erro em criar_locacao_fornecedor: {str(e)}")
        return jsonify({'erro': str(e)}), 500
    

@app.route('/api/enviar_email_fornecedor', methods=['POST'])
@login_required
def enviar_email_fornecedor():
    """
    Envia email de solicitação de locação para fornecedor
    """
    cursor = None
    try:
        # Receber dados do formulário
        email_destinatario = request.form.get('email_destinatario')
        assunto = request.form.get('assunto')
        corpo_html = request.form.get('corpo_html')
        id_demanda = request.form.get('id_demanda')
        id_item_fornecedor = request.form.get('id_item_fornecedor')  # ID_ITEM da TJ_CONTROLE_LOCACAO_ITENS
        
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
        
        # Obter nome do usuário
        nome_usuario = session.get('usuario_nome', 'Administrador')
        
        # Versão texto simples (fallback)
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
        
        # Criar mensagem
        msg = Message(
            subject=assunto,
            recipients=[email_destinatario],
            html=corpo_html,
            body=corpo_texto,
            sender=("TJRO-SEGEOP", "segeop@tjro.jus.br")
        )
        
        # Anexar arquivos
        for anexo in anexos:
            msg.attach(
                anexo['nome'],
                anexo['tipo'],
                anexo['conteudo']
            )
        
        # Enviar email
        mail.send(msg)
        
        # Registrar no banco
        cursor = mysql.connection.cursor()
        
        from pytz import timezone
        tz_manaus = timezone('America/Manaus')
        data_hora_atual = datetime.now(tz_manaus).strftime("%d/%m/%Y %H:%M:%S")
        
        # Inserir registro de email (COM ID_ITEM)
        cursor.execute("""
            INSERT INTO EMAIL_OUTRAS_LOCACOES 
            (ID_AD, ID_ITEM, DESTINATARIO, ASSUNTO, TEXTO, DATA_HORA) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            id_demanda, 
            id_item_fornecedor or 0,  # ID_ITEM (novo campo)
            email_destinatario, 
            assunto, 
            corpo_texto, 
            data_hora_atual
        ))
        
        id_email = cursor.lastrowid
        
        # ===== CORREÇÃO: Atualizar campo SOLICITADO na demanda =====
        cursor.execute("""
            UPDATE ATENDIMENTO_DEMANDAS 
            SET SOLICITADO = 'S' 
            WHERE ID_AD = %s
        """, (id_demanda,))
        
        # ===== NOVO: Atualizar FL_EMAIL na TJ_CONTROLE_LOCACAO_ITENS =====
        if id_item_fornecedor:
            cursor.execute("""
                UPDATE TJ_CONTROLE_LOCACAO_ITENS 
                SET FL_EMAIL = 'S' 
                WHERE ID_ITEM = %s
            """, (id_item_fornecedor,))
        
        mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'id_email': id_email,
            'mensagem': 'Email enviado com sucesso!'
        })
        
    except Exception as e:
        app.logger.error(f"Erro ao enviar email para fornecedor: {str(e)}")
        if cursor:
            mysql.connection.rollback()
        return jsonify({'erro': str(e)}), 500
    finally:
        if cursor:
            cursor.close()

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


#######################################

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
