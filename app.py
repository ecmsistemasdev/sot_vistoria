from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from functools import wraps
import os
from flask_mysqldb import MySQL
import uuid
import base64
from datetime import datetime
from io import BytesIO
from pytz import timezone

app = Flask(__name__)

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
        session['usuario_nome'] = usuario[1]
        session['nivel_acesso'] = usuario[2]
        
        # Retorna dados para salvar no localStorage via JavaScript
        return jsonify({
            'sucesso': True,
            'usuario_id': usuario[0],
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
        SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, v.DATA, v.TIPO, v.STATUS, v.OBS 
        FROM VISTORIAS v
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.STATUS = 'EM_TRANSITO' AND v.TIPO = 'SAIDA'
        ORDER BY v.DATA DESC
    """)
    vistorias_em_transito = cur.fetchall()

    # Buscar vistorias em Pendentes
    cur.execute("""
        SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, v.DATA, v.TIPO, v.STATUS, v.OBS 
        FROM VISTORIAS v
        JOIN TJ_MOTORISTA m ON v.IDMOTORISTA = m.ID_MOTORISTA
        JOIN TJ_VEICULO ve ON v.IDVEICULO = ve.ID_VEICULO
        WHERE v.TIPO IN ('INICIAL', 'CONFIRMACAO')
        ORDER BY v.DATA DESC
    """)
    vistorias_pendentes = cur.fetchall()

    # Buscar vistorias finalizadas (Saidas com devolução ou devoluções)
    cur.execute("""
        SELECT v.IDVISTORIA, m.NM_MOTORISTA as MOTORISTA, CONCAT(ve.DS_MODELO,' - ',ve.NU_PLACA) AS VEICULO, 
        v.DATA, v.TIPO, v.STATUS, v.OBS, (SELECT IDVISTORIA FROM VISTORIAS WHERE VISTORIA_SAIDA_ID = v.IDVISTORIA) AS ID_DEVOLUCAO
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
            ID_MOTORISTA, CAD_MOTORISTA, NM_MOTORISTA, 
            ORDEM_LISTA, SIGLA_SETOR, CAT_CNH, 
            DT_VALIDADE_CNH, ULTIMA_ATUALIZACAO, 
            NU_TELEFONE, OBS_MOTORISTA, ATIVO, ORDEM_LISTA, NOME_ARQUIVO
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
                'nome_arquivo': result[12]
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
            FILE_PDF, NOME_ARQUIVO, ORDEM_LISTA
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'S', %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            novo_id, cad_motorista, nm_motorista, tipo_cadastro_desc, 
            sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
            nu_telefone, obs_motorista, session.get('usuario_id'), 
            dt_transacao, file_blob, nome_arquivo, tipo_cadastro
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
                FILE_PDF = %s, NOME_ARQUIVO = %s, ORDEM_LISTA = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                dt_transacao, file_blob, nome_arquivo, tipo_cadastro, id_motorista
            ))
        else:
            # Update without changing file
            query = """
            UPDATE TJ_MOTORISTA 
            SET CAD_MOTORISTA = %s, NM_MOTORISTA = %s, TIPO_CADASTRO = %s, 
                SIGLA_SETOR = %s, CAT_CNH = %s, DT_VALIDADE_CNH = %s, 
                ULTIMA_ATUALIZACAO = %s, NU_TELEFONE = %s, OBS_MOTORISTA = %s, 
                ATIVO = %s, USUARIO = %s, DT_TRANSACAO = %s, ORDEM_LISTA = %s
            WHERE ID_MOTORISTA = %s
            """
            
            cursor.execute(query, (
                cad_motorista, nm_motorista, tipo_cadastro_desc, 
                sigla_setor, cat_cnh, dt_validade_cnh, ultima_atualizacao, 
                nu_telefone, obs_motorista, ativo, session.get('usuario_id'), 
                dt_transacao, tipo_cadastro, id_motorista
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
           ELSE UPPER(m.NM_MOTORISTA) END AS MOTORISTA, 
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
        CASE WHEN i.ID_MOTORISTA=0 THEN CONCAT('*',i.NC_CONDUTOR,'*') ELSE UPPER(m.NM_MOTORISTA) END AS MOTORISTA, 
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
    query = """
        SELECT i.ID_ITEM, CONCAT(x.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO, 
        CASE WHEN i.DT_INICIAL=i.DT_FINAL THEN i.DT_INICIAL
        ELSE CONCAT(i.DT_INICIAL,' - ',i.DT_FINAL) END AS PERIODO,
        CONCAT(v.DE_REDUZ,' / ',i.DS_VEICULO_MOD) AS VEICULO, 
        CASE WHEN i.ID_MOTORISTA=0 THEN CONCAT('*',i.NC_CONDUTOR,'*') ELSE UPPER(m.NM_MOTORISTA) END AS MOTORISTA,
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
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(query, (id_cl,))
        items = cursor.fetchall()
        cursor.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/rel_locacao_analitico')
@login_required
def rel_locacao_analitico():
    return render_template('rel_locacao_analitico.html')

# @app.route('/api/locacoes_finalizadas/<int:id_cl>')
# @login_required
# def api_locacoes_finalizadas(id_cl):
#     try:
#         cursor = mysql.connection.cursor()
#         query = """
#         SELECT
#            i.ID_ITEM, i.ID_EXERCICIO, x.NU_MES, x.DE_MES,
#            CONCAT(x.DE_MES,'/',i.ID_EXERCICIO) AS MES_ANO,
#            e.NU_EMPENHO, v.ID_VEICULO_LOC, v.DE_VEICULO,
#            i.DS_VEICULO_MOD, i.DT_INICIAL, i.DT_FINAL, 
#            i.HR_INICIAL, i.HR_FINAL, i.QT_DIARIA_KM,
#            i.VL_DK, i.VL_SUBTOTAL, i.VL_DIFERENCA, i.VL_TOTALITEM,
#            i.NU_SEI, i.OBJETIVO, i.SETOR_SOLICITANTE, i.ID_MOTORISTA, 
#            CASE WHEN i.ID_MOTORISTA=0
#            THEN CONCAT('*',i.NC_CONDUTOR,'*')
#            ELSE UPPER(m.NM_MOTORISTA) END AS MOTORISTA, 
#            i.FL_EMAIL, i.KM_RODADO, i.COMBUSTIVEL, i.OBS, i.OBS_DEV
#         FROM TJ_CONTROLE_LOCACAO_ITENS i
#         LEFT JOIN TJ_MOTORISTA m
#         ON m.ID_MOTORISTA = i.ID_MOTORISTA, 
#         TJ_VEICULO_LOCACAO v, TJ_MES x,
#         TJ_CONTROLE_LOCACAO_EMPENHOS e
#         WHERE e.ID_EMPENHO = i.ID_EMPENHO
#         AND x.ID_MES = i.ID_MES
#         AND v.ID_VEICULO_LOC = i.ID_VEICULO_LOC
#         AND i.FL_STATUS = 'F'
#         AND i.ID_CL = %s
#         ORDER BY i.ID_EXERCICIO DESC, i.ID_MES DESC, i.DATA_INICIO DESC, i.DATA_FIM DESC
#         """
#         app.logger.info(f"Executando consulta de locações finalizadas para ID_CL={id_cl}")
#         cursor.execute(query, (id_cl,))
#         locacoes = cursor.fetchall()
#         app.logger.info(f"Encontradas {len(locacoes)} locações finalizadas")
        
#         # Converter para dicionários
#         resultado = []
#         for loc in locacoes:
#             item = {
#                 'ID_ITEM': loc[0],
#                 'ID_EXERCICIO': loc[1],
#                 'NU_MES': loc[2],
#                 'DE_MES': loc[3],
#                 'MES_ANO': loc[4],
#                 'NU_EMPENHO': loc[5],
#                 'ID_VEICULO_LOC': loc[6],
#                 'DE_VEICULO': loc[7],
#                 'DS_VEICULO_MOD': loc[8],
#                 'DT_INICIAL': loc[9] if loc[9] else None,
#                 'DT_FINAL': loc[10] if loc[10] else None,
#                 'HR_INICIAL': loc[11],
#                 'HR_FINAL': loc[12],
#                 'QT_DIARIA_KM': loc[13],
#                 'VL_DK': float(loc[14]) if loc[14] else 0,
#                 'VL_SUBTOTAL': float(loc[15]) if loc[15] else 0,
#                 'VL_DIFERENCA': float(loc[16]) if loc[16] else 0,
#                 'VL_TOTALITEM': float(loc[17]) if loc[17] else 0,
#                 'NU_SEI': loc[18],
#                 'OBJETIVO': loc[19],
#                 'SETOR_SOLICITANTE': loc[20],
#                 'ID_MOTORISTA': loc[21],
#                 'MOTORISTA': loc[22],
#                 'FL_EMAIL': loc[23],
#                 'KM_RODADO': loc[24],
#                 'COMBUSTIVEL': loc[25],
#                 'OBS': loc[26],
#                 'OBS_DEV': loc[27]
#             }
#             resultado.append(item)
        
#         cursor.close()
#         return jsonify(resultado)
#     except Exception as e:
#         app.logger.error(f"Erro ao buscar locações em trânsito: {str(e)}")
#         return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
