from flask import Flask, render_template, redirect, request, make_response, jsonify, flash, session
from flask_mail import Mail, Message
from flask_cors import CORS
from flask_mysqldb import MySQL
from dotenv import load_dotenv
from datetime import datetime
from pytz import timezone
import mercadopago
import requests
import hashlib
import pdfkit
import os
import re
import random
import string
import json
import uuid
import logging
import pytz

load_dotenv()  # Carrega as variáveis do arquivo .env

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

sdk = mercadopago.SDK(os.getenv('MP_ACCESS_TOKEN'))

app.secret_key = os.getenv('SECRET_KEY')
CORS(app)

# Configuração do Flask-Mail
#app.config['MAIL_SERVER'] = os.getenv('SMTP_SERVER')  # Substitua pelo seu servidor SMTP
#app.config['MAIL_PORT'] = os.getenv('SMTP_PORT') 
#app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER') 
#app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASSWORD') 
#app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')  # Substitua pelo seu servidor SMTP
app.config['MAIL_PORT'] = os.getenv('MAIL_PORT') 
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME') 
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD') 
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
app.config['MAIL_USE_TLS'] = True 
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_MAX_EMAILS'] = None
app.config['MAIL_TIMEOUT'] = 10  # segundos
app.config['MP_ACCESS_TOKEN'] = os.getenv('MP_ACCESS_TOKEN')

mail = Mail(app)

# Configuração MySQL
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')

mysql = MySQL(app)

#sdk = mercadopago.SDK(os.getenv('MP_ACCESS_TOKEN2'))

# Global variables for the receipt
receipt_data = {
    'titulo': 'Comprovante de Inscrição',
    'data': '14/01/2025',
    'evento': '4º DESAFIO 200K PORTO VELHO-HUMAITÁ - 2025',
    'endereco': 'AV. Jorge Teixeira, Espaço Alternativo - Porto Velho/RO',
    'dataevento': '04, 05 e 06/07/2025',
    'participante': 'ELIENAI CARVALHO MOMTEIRO',
    'km': 'Solo - 200 km',
    'valor': 'R$ 500,00',
    'inscricao': '123455456456',    
    'obs': 'Observações importantes sobre o evento vão aqui.'
}

var_email = ""

def fn_email(valor):
    global var_email
    var_email = valor

@app.route("/")
def index():
    return render_template("index.html")

@app.route('/backyard2025/resultado')
def backyard2025_resultado():
    # Obter parâmetros de filtro
    sexo_filter = request.args.get('sexo', '')
    tipo_corrida_filter = request.args.get('tipo_corrida', '')
    
    # Iniciar a consulta base
    query = """
        SELECT idatleta, concat(lpad(cast(nrpeito as char(3)),3,0),' - ', nome) as atleta, 
        sexo, tipo_corrida, 
        case when nr_voltas>0 then nr_voltas else 'DNF' end as nvoltas,
        case when nr_voltas>0 then cast((nr_voltas * 6706) as char) else 'DNF' end as km
        FROM 2025_atletas
        WHERE 1=1
    """
    
    # Adicionar filtros se fornecidos
    if sexo_filter:
        query += f" AND sexo = '{sexo_filter}'"
    if tipo_corrida_filter:
        query += f" AND tipo_corrida = '{tipo_corrida_filter}'"
    
    # Ordenação
    query += " ORDER BY nr_voltas DESC, nome"
    
    # Executar a consulta
    cursor = mysql.connection.cursor()
    cursor.execute(query)
    atletas = cursor.fetchall()
    
    # Obter listas únicas para os filtros de dropdown
    cursor.execute("SELECT DISTINCT sexo FROM 2025_atletas ORDER BY sexo")
    sexos = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT tipo_corrida FROM 2025_atletas ORDER BY tipo_corrida")
    tipos_corrida = [row[0] for row in cursor.fetchall()]
    
    cursor.close()
    
    return render_template(
        'backyard2025resultado.html', 
        atletas=atletas, 
        sexos=sexos, 
        tipos_corrida=tipos_corrida,
        sexo_filter=sexo_filter,
        tipo_corrida_filter=tipo_corrida_filter
    )


@app.route('/listar-estados', methods=['GET'])
def listar_estados():
    try:
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT uf, nome 
            FROM estado 
            ORDER BY nome
        """)
        
        estados_tuplas = cursor.fetchall()
        
        estados = []
        for estado in estados_tuplas:
            estados.append({
                'uf': estado[0],
                'nome': estado[1]
            })
            
        cursor.close()
        
        return jsonify({
            'success': True,
            'estados': estados
        })
    except Exception as e:
        app.logger.error(f"Erro ao buscar estados: {e}")
        return jsonify({
            'success': False,
            'mensagem': 'Erro ao buscar estados'
        }), 500

@app.route('/listar-cidades', methods=['GET'])
def listar_cidades():
    try:
        uf = request.args.get('uf')
        
        if not uf:
            return jsonify({
                'success': False,
                'mensagem': 'UF não fornecida'
            }), 400
        
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT c.id_cidade, c.descricao
            FROM cidade c
            JOIN estado e ON c.uf = e.uf
            WHERE e.uf = %s
            ORDER BY c.descricao
        """, (uf,))
        
        cidades_tuplas = cursor.fetchall()  # Armazene os resultados primeiro
        
        cidades = []
        for cidade in cidades_tuplas:
            cidades.append({
                'id_cidade': cidade[0],
                'descricao': cidade[1]
            })
            
        cursor.close()  # Feche o cursor depois de processar os resultados

        return jsonify({
            'success': True,
            'cidades': cidades
        })
    except Exception as e:
        app.logger.error(f"Erro ao buscar cidades para UF {uf}: {e}")
        return jsonify({
            'success': False,
            'mensagem': f'Erro ao buscar cidades para UF {uf}'
        }), 500

# Funções auxiliares do backyard
def calculate_seconds_difference(start_time_str, end_time_str):
    start_time = datetime.strptime(start_time_str, '%d/%m/%Y %H:%M:%S')
    end_time = datetime.strptime(end_time_str, '%d/%m/%Y %H:%M:%S')
    return (end_time - start_time).total_seconds()

def format_time_difference(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

@app.route('/desafio200k/regulamento')
def regulamento200k():
    return render_template('regulamento200k.html')
    
@app.route('/corracomultra')
def corracomultra():
    return render_template('corracomultra.html')


# Rotas do backyard
@app.route('/backyard/lancamento')
def backyard_lancamento():
    return render_template('backyardlancamento.html')

@app.route('/backyard/pesquisar_atleta/<nrpeito>')
def pesquisar_atleta(nrpeito):
    try:
        cur = mysql.connection.cursor()

        query = """
            SELECT la.id, la.idlargada, a.idatleta, a.nome, a.nrpeito,
                la.largada, a.tipo_corrida, la.nulargada, la.parcial, la.chegada,
                CONCAT(LPAD(CAST(a.nrpeito AS CHAR(3)),3,'0'),' - ', a.nome) as atleta
            FROM bm_largadas_atletas la, bm_atletas a
            WHERE (la.chegada = '' OR la.chegada IS NULL)
                AND la.idlargada = (
                    SELECT MAX(idlargada) 
                    FROM bm_largadas_atletas
                    WHERE (chegada = '' OR chegada IS NULL)
                    AND idatleta = a.idatleta
                )
                AND la.idatleta = a.idatleta
                AND a.nrpeito = %s
        """
        
        cur.execute(query, (nrpeito,))
        result = cur.fetchone()
        
        if result:
            columns = [desc[0] for desc in cur.description]
            result_dict = dict(zip(columns, result))
            
            return jsonify({
                'success': True,
                'atleta': result_dict['atleta'],
                'data': result_dict
            })
        else:
            cur.execute("SELECT * FROM bm_atletas WHERE nrpeito = %s", (nrpeito,))
            atleta_exists = cur.fetchone()
            
            return jsonify({
                'success': False,
                'message': 'Atleta não encontrado'
            })
            
    except Exception as e:
        print(f"Erro na consulta: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })
    finally:
        cur.close()

@app.route('/backyard/lancar_chegada', methods=['POST'])
def lancar_chegada():
    try:
        #data = request.get_json()
        #nrpeito = data['nrpeito']
        #chegada = data['chegada']
        
        data = request.get_json()
        nrpeito = data['nrpeito']
        chegada = data['chegada'].replace(', ', ' ')  # Remove a vírgula e mantém apenas um espaço


        cur = mysql.connection.cursor()
        
        # Buscar dados do atleta
        cur.execute("""
            SELECT la.*, a.tipo_corrida 
            FROM bm_largadas_atletas la, bm_atletas a
            WHERE la.idatleta = a.idatleta
            AND a.nrpeito = %s
            AND (la.chegada = '' OR la.chegada IS NULL)
        """, (nrpeito,))
        
        result = cur.fetchone()
        if not result:
            return jsonify({
                'success': False,
                'error': 'Atleta não encontrado'
            })
            
        columns = [desc[0] for desc in cur.description]
        atleta = dict(zip(columns, result))
        
        # Próxima ordem de chegada
        cur.execute("""
            SELECT COALESCE(MAX(ordem_chegada),0) as ID 
            FROM bm_largadas_atletas 
            WHERE idlargada = %s
        """, (atleta['idlargada'],))
        
        result = cur.fetchone()
        ordem_chegada = (result[0] or 0) + 1
        
        # Cálculo de tempo e status
        segundos = calculate_seconds_difference(atleta['largada'], chegada)
        tempo_chegada = format_time_difference(segundos)
        
        vstatus = 'D' if segundos > 3599 else 'A'
        
        if atleta['idlargada'] == 3 and atleta['tipo_corrida'] == 'Três voltas':
            vstatus = 'D'
            
        # Atualizar registro
        cur.execute("""
            UPDATE bm_largadas_atletas
            SET 
                chegada = %s,
                tempochegada = %s,
                ordem_chegada = %s,
                usuario_chegada = %s
            WHERE id = %s
        """, (chegada, tempo_chegada, ordem_chegada, 'ADM', atleta['id']))
        
        mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'message': 'Chegada lançada com sucesso'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })
    finally:
        cur.close()

# Rota para renderizar a página eventos.html
@app.route('/eventos')
def eventos():
    return render_template('eventos.html')

# Get all eventos
@app.route('/api/eventos')
def get_eventos():
    cur = mysql.connection.cursor()
    cur.execute("SELECT IDEVENTO, DESCRICAO FROM EVENTO ORDER BY DTINICIO DESC")
    eventos = [{'IDEVENTO': row[0], 'DESCRICAO': row[1]} for row in cur.fetchall()]
    cur.close()
    return jsonify(eventos)

# Get specific evento
@app.route('/api/eventos/<int:evento_id>')
def get_evento(evento_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT IDEVENTO, DESCRICAO, DTINICIO, DTFIM, HRINICIO, 
               INICIO_INSCRICAO, FIM_INSCRICAO, 
               INICIO_INSCRICAO_EXT, FIM_INSCRICAO_EXT 
        FROM EVENTO WHERE IDEVENTO = %s
    """, (evento_id,))
    row = cur.fetchone()
    cur.close()
    
    if row:
        evento = {
            'IDEVENTO': row[0],
            'DESCRICAO': row[1],
            'DTINICIO': row[2], # .strftime('%d/%m/%Y') if row[2] else '',
            'DTFIM': row[3], #.strftime('%d/%m/%Y') if row[3] else '',
            'HRINICIO': row[4], #.strftime('%H:%M') if row[4] else '',
            'INICIO_INSCRICAO': row[5], #.strftime('%d/%m/%Y %H:%M:%S') if row[5] else '',
            'FIM_INSCRICAO': row[6], #.strftime('%d/%m/%Y %H:%M:%S') if row[6] else '',
            'INICIO_INSCRICAO_EXT': row[7], #.strftime('%d/%m/%Y %H:%M:%S') if row[7] else '',
            'FIM_INSCRICAO_EXT': row[8] #.strftime('%d/%m/%Y %H:%M:%S') if row[8] else ''
        }
        return jsonify(evento)
    return jsonify(None)

# Update evento
@app.route('/api/eventos', methods=['PUT'])
def update_evento():
    data = request.json
    
    # Converter as datas do formato brasileiro para o formato do MySQL
    dtinicio = data['DTINICIO'] #datetime.strptime(data['DTINICIO'], '%d/%m/%Y').strftime('%Y-%m-%d')
    dtfim = data['DTFIM'] #datetime.strptime(data['DTFIM'], '%d/%m/%Y').strftime('%Y-%m-%d')
    hrinicio = data['HRINICIO']
    inicio_inscricao = data['INICIO_INSCRICAO'] #datetime.strptime(data['INICIO_INSCRICAO'], '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
    fim_inscricao = data['FIM_INSCRICAO'] #datetime.strptime(data['FIM_INSCRICAO'], '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
    inicio_inscricao_ext = data['INICIO_INSCRICAO_EXT'] #datetime.strptime(data['INICIO_INSCRICAO_EXT'], '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
    fim_inscricao_ext = data['FIM_INSCRICAO_EXT'] #datetime.strptime(data['FIM_INSCRICAO_EXT'], '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
    
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE EVENTO 
        SET DESCRICAO = %s, 
            DTINICIO = %s,
            DTFIM = %s,
            HRINICIO = %s,
            INICIO_INSCRICAO = %s,
            FIM_INSCRICAO = %s,
            INICIO_INSCRICAO_EXT = %s,
            FIM_INSCRICAO_EXT = %s
        WHERE IDEVENTO = %s
    """, (
        data['DESCRICAO'], dtinicio, dtfim, hrinicio,
        inicio_inscricao, fim_inscricao,
        inicio_inscricao_ext, fim_inscricao_ext,
        data['IDEVENTO']
    ))
    mysql.connection.commit()
    cur.close()
    return jsonify({'message': 'Evento atualizado com sucesso'})

# Get modalidades for evento
@app.route('/api/modalidades/<int:evento_id>')
def get_modalidades(evento_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT IDITEM, DESCRICAO, 
               FORMAT(VLINSCRICAO, 2) as VLINSCRICAO, 
               FORMAT(VLTAXA, 2) as VLTAXA 
        FROM EVENTO_MODALIDADE 
        WHERE IDEVENTO = %s
    """, (evento_id,))
    modalidades = [
        {
            'IDITEM': row[0],
            'DESCRICAO': row[1],
            'VLINSCRICAO': row[2],
            'VLTAXA': row[3]
        } for row in cur.fetchall()
    ]
    cur.close()
    return jsonify(modalidades)

# Get specific modalidade
@app.route('/api/modalidade/<int:iditem>')
def get_modalidade(iditem):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT IDITEM, DESCRICAO, 
               FORMAT(VLINSCRICAO, 2) as VLINSCRICAO, 
               FORMAT(VLTAXA, 2) as VLTAXA 
        FROM EVENTO_MODALIDADE 
        WHERE IDITEM = %s
    """, (iditem,))
    row = cur.fetchone()
    cur.close()
    
    if row:
        modalidade = {
            'IDITEM': row[0],
            'DESCRICAO': row[1],
            'VLINSCRICAO': row[2],
            'VLTAXA': row[3]
        }
        return jsonify(modalidade)
    return jsonify(None)

# Update modalidade
@app.route('/api/modalidade', methods=['PUT'])
def update_modalidade():
    data = request.json
    
    # Converter valores monetários (remove R$ e vírgulas)
    vlinscricao = float(data['VLINSCRICAO'].replace('R$', '').replace('.', '').replace(',', '.').strip())
    vltaxa = float(data['VLTAXA'].replace('R$', '').replace('.', '').replace(',', '.').strip())
    
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE EVENTO_MODALIDADE 
        SET DESCRICAO = %s,
            VLINSCRICAO = %s,
            VLTAXA = %s
        WHERE IDITEM = %s
    """, (data['DESCRICAO'], vlinscricao, vltaxa, data['IDITEM']))
    mysql.connection.commit()
    cur.close()
    return jsonify({'message': 'Modalidade atualizada com sucesso'})

@app.route("/checkout")
def checkout():

    # Get values from session
    vlinscricao = session.get('valoratual', 0)
    vltaxa = session.get('valortaxa', 0)
    valor_total = float(vlinscricao) + float(vltaxa)
    
    # Obter a chave pública do Mercado Pago das variáveis de ambiente
    mp_public_key = os.environ.get('MP_PUBLIC_KEY')
    
    return render_template('checkout.html', 
                         valor_inscricao=vlinscricao,
                         valor_taxa=vltaxa,
                         valor_total=valor_total,
                         mp_public_key=mp_public_key)

# @app.route('/process_payment', methods=['POST'])
# def process_payment():
#     try:
#         # Configurar log detalhado
#         app.logger.setLevel(logging.INFO)
        
#         # Receber dados do pagamento
#         payment_data = request.json
#         app.logger.info("Dados completos recebidos:")
#         app.logger.info(json.dumps(payment_data, indent=2))

#         installments = payment_data.get('installments', 1)
#         transaction_amount = payment_data.get('transaction_amount', 0)

#         # device_id = payment_data.get('device_id')
#         # app.logger.info(f"Device ID recebido: {device_id}")

#         # if not device_id:
#         #     app.logger.error("Device ID está ausente ou vazio")
#         #     return jsonify({"error": "Device ID é obrigatório"}), 400
       
        
#         # Validação de campos obrigatórios
#         required_fields = [
#             'token', 
#             'transaction_amount', 
#             'installments', 
#             'payment_method_id',
#             'payer'
#         ]
        
#         for field in required_fields:
#             if field not in payment_data:
#                 app.logger.error(f"Campo obrigatório ausente: {field}")
#                 raise ValueError(f"Campo obrigatório ausente: {field}")
        
#         # Extrair e validar dados importantes
#         #installments = int(payment_data.get('installments', 1))
#         #transaction_amount = round(float(payment_data['transaction_amount']), 2)
        
#         # Extrair dados do participante
#         valor_total = round(float(payment_data.get('valor_total', 0)), 2)
#         valor_atual = round(float(payment_data.get('valor_atual', 0)), 2)
#         valor_taxa = round(float(payment_data.get('valor_taxa', 0)), 2)
        
#         # Dados adicionais do participante
#         camisa = payment_data.get('camiseta')
#         apoio = payment_data.get('apoio')
#         equipe = payment_data.get('equipe')
#         equipe200 = payment_data.get('nome_equipe')
#         integrantes = payment_data.get('integrantes')
        
#         # Preparar dados da sessão
#         session['valorTotal'] = transaction_amount
#         session['numeroParcelas'] = installments
#         session['valorParcela'] = transaction_amount / installments if installments > 0 else transaction_amount
#         session['valorTotalsemJuros'] = valor_total
#         session['valorAtual'] = valor_atual
#         session['valorTaxa'] = valor_taxa
#         session['formaPagto'] = 'CARTAO DE CREDITO'
#         session['Camisa'] = camisa
#         session['Equipe'] = equipe
#         session['Apoio'] = apoio
#         session['Equipe200'] = equipe200
#         session['Integrantes'] = integrantes
        
#         # Gerar referência externa única
#         external_reference = str(uuid.uuid4())
        
#         # Preparar dados do item
#         item_details = {
#             "id": "DESAFIO_200K",
#             "title": "Inscrição Desafio 200k",
#             "description": "Inscrição para 4º Desafio 200km",
#             "category_id": "SPORTS_EVENT",
#             "quantity": 1,
#             "currency_id": "BRL",
#             "unit_price": valor_atual,
#             "total_amount": transaction_amount
#         }
        
#         # Preparar preferência de pagamento
#         preference_data = {
#             "items": [item_details],
#             "notification_url": "https://ecmrun.com.br/webhook",
#             "external_reference": external_reference
#         }
        
#         try:
#             preference_response = sdk.preference().create(preference_data)
#             if "response" not in preference_response:
#                 app.logger.error("Erro ao criar preferência de pagamento")
#                 raise ValueError("Erro ao criar preferência de pagamento")
#         except Exception as pref_error:
#             app.logger.error(f"Erro na criação da preferência: {str(pref_error)}")
#             raise
        
#         # Preparar dados do pagamento
#         payment_info = {
#             "transaction_amount": transaction_amount,
#             "token": payment_data['token'],
#             "description": "Inscrição Desafio 200k",
#             "statement_descriptor": "ECMRUN DESAFIO 200K",
#             "installments": installments,
#             "payment_method_id": payment_data['payment_method_id'],
#             "external_reference": external_reference,
#             "notification_url": "https://ecmrun.com.br/webhook",
#             "payer": {
#                 "email": payment_data['payer']['email'],
#                 "identification": {
#                     "type": payment_data['payer']['identification']['type'],
#                     "number": payment_data['payer']['identification']['number']
#                 },
#                 "first_name": payment_data['payer']['first_name'],
#                 "last_name": payment_data['payer']['last_name']
#             },
#             "additional_info": {
#                 "items": [item_details],
#                 "payer": {
#                     "first_name": payment_data['payer']['first_name'],
#                     "last_name": payment_data['payer']['last_name'],
#                     "registration_date": datetime.now().isoformat()
#                 },
#                 "ip_address": request.remote_addr,
#                 "user_agent": str(request.user_agent)
#             }
#         }
        
#         app.logger.info("Dados do pagamento para processamento:")
#         app.logger.info(json.dumps(payment_info, indent=2))
        
#         # Processar pagamento
#         try:
#             payment_response = sdk.payment().create(payment_info)
            
#             app.logger.info("Resposta do pagamento:")
#             app.logger.info(json.dumps(payment_response, indent=2))
            
#             if "response" not in payment_response:
#                 error_msg = payment_response.get("message", "Erro desconhecido")
#                 app.logger.error(f"Erro no processamento do pagamento: {error_msg}")
#                 return jsonify({
#                     "error": "Erro ao processar pagamento",
#                     "details": error_msg
#                 }), 400
            
#             payment_data = payment_response["response"]
            
#             # Verificar status do pagamento
#             if payment_data.get("status") == "approved":
#                 # Lógica adicional para pagamento aprovado
#                 try:
#                     # Exemplo de chamada para lançar pagamento
#                     verification_response = requests.get(
#                         f'/lanca-pagamento-cartao/{payment_data["id"]}', 
#                         headers={'Accept': 'application/json'}
#                     )
                    
#                     if verification_response.status_code != 200:
#                         app.logger.warning(f"Erro na verificação do pagamento: {verification_response.text}")
                
#                 except Exception as verification_error:
#                     app.logger.error(f"Erro na verificação do pagamento: {str(verification_error)}")
                
#                 return jsonify(payment_data), 200
#             else:
#                 app.logger.warning(f"Pagamento não aprovado. Status: {payment_data.get('status')}")
#                 return jsonify({
#                     "message": "Pagamento não aprovado",
#                     "status": payment_data.get("status")
#                 }), 400
        
#         except Exception as payment_error:
#             app.logger.error(f"Erro no processamento do pagamento: {str(payment_error)}")
#             return jsonify({
#                 "error": "Erro interno no processamento do pagamento",
#                 "details": str(payment_error)
#             }), 500
    
#     except ValueError as validation_error:
#         app.logger.error(f"Erro de validação: {str(validation_error)}")
#         return jsonify({"error": str(validation_error)}), 400
    
#     except Exception as general_error:
#         app.logger.error(f"Erro geral no processamento: {str(general_error)}")
#         return jsonify({"error": "Erro interno no servidor"}), 500

####################################

# @app.route('/process_payment', methods=['POST'])
# def process_payment():
#     try:
#         app.logger.info("Dados recebidos:")
#         payment_data = request.json
#         app.logger.info(payment_data)
        
#         installments = payment_data.get('installments', 1)
#         transaction_amount = payment_data.get('transaction_amount', 0)
        
#         # Round to 2 decimal places to avoid floating point precision issues
#         valor_total = round(float(payment_data.get('valor_total', 0)), 2)
#         valor_atual = round(float(payment_data.get('valor_atual', 0)), 2)
#         valor_taxa = round(float(payment_data.get('valor_taxa', 0)), 2)
#         camisa = payment_data.get('camiseta')
#         apoio = payment_data.get('apoio')
#         equipe = payment_data.get('equipe')
#         equipe200 = payment_data.get('nome_equipe')
#         integrantes = payment_data.get('integrantes')

#         session['valorTotal'] = transaction_amount #valor_total
#         session['numeroParcelas'] = installments
#         session['valorParcela'] = transaction_amount / installments if installments > 0 else transaction_amount
#         session['valorTotalsemJuros'] = valor_total
#         session['valorAtual'] = valor_atual
#         session['valorTaxa'] = valor_taxa
#         session['formaPagto'] = 'CARTÃO DE CRÉDITO'
#         session['Camisa'] = camisa
#         session['Equipe'] = equipe
#         session['Apoio'] = apoio
#         session['Equipe200'] = equipe200
#         session['Integrantes'] = integrantes

#         # Validar dados recebidos
#         required_fields = [
#             'token', 
#             'transaction_amount', 
#             'installments', 
#             'payment_method_id',
#             'payer'
#         ]
        
#         for field in required_fields:
#             if field not in payment_data:
#                 raise ValueError(f"Campo obrigatório ausente: {field}")

#         # Gerar referência externa única
#         external_reference = str(uuid.uuid4())
        
#         # Criar preferência de pagamento
#         item_details = {
#             "id": "DESAFIO_200K",
#             "title": "Inscrição Desafio 200k",
#             "description": "Inscrição para 4º Desafio 200km",
#             "category_id": "SPORTS_EVENT",
#             "quantity": 1,
#             "currency_id": "BRL",
#             "unit_price": valor_atual,
#             "total_amount": transaction_amount
#         }
        
#         # Preparar preferência de pagamento
#         preference_data = {
#             "items": [item_details],
#             "notification_url": "https://ecmrun.com.br/webhook",
#             "external_reference": external_reference
#         }
        
#         # Criar preferência
#         preference_response = sdk.preference().create(preference_data)
        
#         if "response" not in preference_response:
#             raise ValueError("Erro ao criar preferência de pagamento")
            

#         payment_info = {
#             "transaction_amount": transaction_amount,
#             "token": payment_data['token'],
#             "description": "Inscrição Desafio 200k",
#             "statement_descriptor": "ECMRUN DESAFIO 200K",
#             "installments": installments,
#             "payment_method_id": payment_data['payment_method_id'],
#             "external_reference": external_reference,
#             "notification_url": "https://ecmrun.com.br/webhook",
#             "payer": {
#                 "email": payment_data['payer']['email'],
#                 "identification": {
#                     "type": payment_data['payer']['identification']['type'],
#                     "number": payment_data['payer']['identification']['number']
#                 },
#                 "first_name": payment_data['payer']['first_name'],
#                 "last_name": payment_data['payer']['last_name']
#             },
#             "additional_info": {
#                 "items": [item_details],
#                 "payer": {
#                     "first_name": payment_data['payer']['first_name'],
#                     "last_name": payment_data['payer']['last_name'],
#                     "registration_date": datetime.now().isoformat()
#                 },
#                 "ip_address": request.remote_addr,
#                 "user_agent": str(request.user_agent)
#             }
#         }

#         app.logger.info("Dados do pagamento:")
#         app.logger.info(payment_info)
        
#         # Processar pagamento
#         payment_response = sdk.payment().create(payment_info)
        
#         app.logger.info("Resposta do pagamento:")
#         app.logger.info(payment_response)
        
#         if "response" not in payment_response:
#             return jsonify({
#                 "error": "Erro ao processar pagamento",
#                 "details": payment_response.get("message", "Erro desconhecido")
#             }), 400
            
#         return jsonify(payment_response["response"]), 200
        
#     except ValueError as e:
#         app.logger.error(f"Erro de validação: {str(e)}")
#         return jsonify({"error": str(e)}), 400
#     except Exception as e:
#         app.logger.error(f"Erro no processamento: {str(e)}")
#         return jsonify({"error": str(e)}), 400



@app.route('/process_payment', methods=['POST'])
def process_payment():
    try:
        app.logger.info("Dados recebidos:")
        payment_data = request.json
        # Log sensitive data securely
        safe_data = {**payment_data}
        if 'token' in safe_data:
            safe_data['token'] = '***HIDDEN***'
        if 'payer' in safe_data and 'identification' in safe_data['payer']:
            safe_data['payer']['identification']['number'] = '***HIDDEN***'
        app.logger.info(safe_data)
        
        # Extract data with proper error handling
        try:
            installments = int(payment_data.get('installments', 1))
            transaction_amount = float(payment_data.get('transaction_amount', 0))
            
            # Round to 2 decimal places to avoid floating point precision issues
            valor_total = round(float(payment_data.get('valor_total', 0)), 2)
            valor_atual = round(float(payment_data.get('valor_atual', 0)), 2)
            valor_taxa = round(float(payment_data.get('valor_taxa', 0)), 2)
            
            # Ensure transaction_amount matches valor_total
            if abs(transaction_amount - valor_total) > 0.01:
                app.logger.warning(f"Discrepância entre transaction_amount ({transaction_amount}) e valor_total ({valor_total})")
                # Use valor_total as the source of truth
                transaction_amount = valor_total
                
            # Store other data safely
            idatleta = payment_data.get('idAtleta')
            vCPF = payment_data.get('CPF')
            camisa = payment_data.get('camiseta', '')
            apoio = payment_data.get('apoio', '')
            equipe = payment_data.get('equipe', '')
            equipe200 = payment_data.get('nome_equipe', '')
            integrantes = payment_data.get('integrantes', '')
        except (ValueError, TypeError) as e:
            raise ValueError(f"Erro ao processar valores numéricos: {str(e)}")

        # Store session data
        session['valorTotal'] = transaction_amount
        session['numeroParcelas'] = installments
        session['valorParcela'] = transaction_amount / installments if installments > 0 else transaction_amount
        session['valorTotalsemJuros'] = valor_total
        session['valorAtual'] = valor_atual
        session['valorTaxa'] = valor_taxa
        session['formaPagto'] = 'CARTÃO DE CRÉDITO'
        session['Camisa'] = camisa
        session['Equipe'] = equipe
        session['Apoio'] = apoio
        session['Equipe200'] = equipe200
        session['Integrantes'] = integrantes
        session['idAtleta'] = idatleta
        session['CPF'] = vCPF

        # Validar dados recebidos
        required_fields = [
            'token', 
            'transaction_amount', 
            'installments', 
            'payment_method_id',
            'payer'
        ]
        
        for field in required_fields:
            if field not in payment_data:
                raise ValueError(f"Campo obrigatório ausente: {field}")
        
        # Validate payer data
        if not payment_data['payer'].get('email'):
            raise ValueError("Email do pagador é obrigatório")
        
        if 'identification' not in payment_data['payer']:
            raise ValueError("Identificação do pagador é obrigatória")
        
        if not payment_data['payer']['identification'].get('type') or not payment_data['payer']['identification'].get('number'):
            raise ValueError("Tipo e número de documento são obrigatórios")

        # Gerar referência externa única
        external_reference = str(uuid.uuid4())
        
        # Criar preferência de pagamento
        item_details = {
            "id": "DESAFIO_200K",
            "title": "Inscrição Desafio 200k",
            "description": "Inscrição para 4º Desafio 200km",
            "category_id": "SPORTS_EVENT",
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": valor_atual,
            "total_amount": transaction_amount
        }
        
        # Preparar preferência de pagamento
        preference_data = {
            "items": [item_details],
            "notification_url": "https://ecmrun.com.br/webhook",
            "external_reference": external_reference
        }
        
        # Criar preferência
        try:
            preference_response = sdk.preference().create(preference_data)
            
            if "response" not in preference_response:
                error_message = preference_response.get("message", "Erro desconhecido na criação da preferência")
                app.logger.error(f"Erro na preferência: {error_message}")
                raise ValueError(f"Erro ao criar preferência de pagamento: {error_message}")
        except Exception as e:
            app.logger.error(f"Exceção ao criar preferência: {str(e)}")
            raise ValueError(f"Erro ao criar preferência de pagamento: {str(e)}")

        payment_info = {
            "transaction_amount": transaction_amount,
            "token": payment_data['token'],
            "description": "Inscrição Desafio 200k",
            "statement_descriptor": "ECMRUN DESAFIO 200K",
            "installments": installments,
            "payment_method_id": payment_data['payment_method_id'],
            "external_reference": external_reference,
            "notification_url": "https://ecmrun.com.br/webhook",
            "payer": {
                "email": payment_data['payer']['email'],
                "identification": {
                    "type": payment_data['payer']['identification']['type'],
                    "number": payment_data['payer']['identification']['number']
                },
                "first_name": payment_data['payer']['first_name'],
                "last_name": payment_data['payer']['last_name']
            },
            "additional_info": {
                "items": [{
                    "id": "DESAFIO_200K",
                    "title": "Inscrição Desafio 200k",
                    "description": "Inscrição para 4º Desafio 200km",
                    "category_id": "SPORTS_EVENT",
                    "quantity": 1,
                    "unit_price": valor_atual
                }],
                "payer": {
                    "first_name": payment_data['payer']['first_name'],
                    "last_name": payment_data['payer']['last_name'],
                    "registration_date": datetime.now().isoformat()
                },
                "ip_address": request.remote_addr
            }
        }

        # Log payment info (exclude sensitive data)
        safe_payment_info = {**payment_info}
        safe_payment_info['token'] = '***HIDDEN***'
        safe_payment_info['payer']['identification']['number'] = '***HIDDEN***'
        app.logger.info("Dados do pagamento:")
        app.logger.info(safe_payment_info)

        # Processar pagamento
        try:
            payment_response = sdk.payment().create(payment_info)
            
            app.logger.info("Resposta do pagamento:")
            app.logger.info(payment_response)
            
            if "response" not in payment_response:
                error_details = payment_response.get("cause", [{}])
                error_message = "Erro desconhecido"
                
                if isinstance(error_details, list) and len(error_details) > 0:
                    error_message = error_details[0].get("description", "Erro desconhecido")
                
                return jsonify({
                    "error": "Erro ao processar pagamento",
                    "details": error_message
                }), 400
                
            payment_data = payment_response["response"]

            # Comentado para testes, mas precisa de um retorno
            # if payment_data.get("status") == "approved":
            #     ...
            # else:
            #     ...
            
            # Adicione este retorno para substituir o bloco comentado
            return jsonify(payment_data), 200        
            
        except Exception as e:
            app.logger.error(f"Exceção ao processar pagamento: {str(e)}")
            return jsonify({
                "error": "Erro ao processar pagamento",
                "details": str(e)
            }), 400
        
    except ValueError as e:
        app.logger.error(f"Erro de validação: {str(e)}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Erro no processamento: {str(e)}")
        return jsonify({"error": str(e)}), 400

def get_receipt_data(payment_id):
    """Função separada para buscar dados do comprovante"""
    try:
        cur = mysql.connection.cursor()
        cur.execute('''
            SELECT I.DTPAGAMENTO, E.DESCRICAO, E.LOCAL, 
                CONCAT(E.DTINICIO,' ',E.HRINICIO,' - ',E.DTFIM) as DTEVENTO,
                CONCAT(A.NOME,' ',A.SOBRENOME) as NOME_COMPLETO, 
                CONCAT(M.DISTANCIA,' / ',M.DESCRICAO) AS DISTANCIA,
                I.VALOR, I.VALOR_PGTO, I.FORMAPGTO, I.IDPAGAMENTO
            FROM ecmrun.INSCRICAO I
            JOIN ecmrun.ATLETA A ON A.IDATLETA = I.IDATLETA
            JOIN ecmrun.EVENTO E ON E.IDEVENTO = I.IDEVENTO
            JOIN ecmrun.EVENTO_MODALIDADE M ON M.IDITEM = I.IDITEM
            WHERE I.FLSTATUS = 'CONFIRMADO'
            AND I.IDPAGAMENTO = %s
        ''', (payment_id,))
        
        data = cur.fetchone()
        cur.close()
        return data
    except Exception as e:
        app.logger.error(f"Erro ao buscar dados: {str(e)}")
        raise

def send_organizer_notification(receipt_data):
    try:
        msg = Message(
            f'Nova Inscrição - 4º Desafio 200k - ID {receipt_data["inscricao"]}',
            sender=('ECM Run', 'ecmsistemasdeveloper@gmail.com'),
            recipients=['kelioesteves@hotmail.com']
            #recipients=['ecmsistemasdeveloper@gmail.com']
        )
        
        # Render the organizer notification template with receipt data
        msg.html = render_template('organizer_email.html', **receipt_data)
        mail.send(msg)
        app.logger.info("Notificação enviada para o organizador")
        return True
        
    except Exception as e:
        app.logger.error(f"Erro ao enviar notificação para o organizador: {str(e)}")
        return False


@app.route('/comprovante/<int:payment_id>')
def comprovante(payment_id):
    try:
        
        app.logger.info(f"Payment ID: {payment_id}")
        
        cur = mysql.connection.cursor()
        # Execute a SQL com o payment_id
        cur.execute('''
            SELECT I.DTPAGAMENTO, E.DESCRICAO, E.LOCAL, 
                CONCAT(E.DTINICIO,' ',E.HRINICIO,' - ',E.DTFIM) as DTEVENTO,
                CONCAT(A.NOME,' ',A.SOBRENOME) as NOME_COMPLETO, 
                CONCAT(M.DISTANCIA,' / ',M.DESCRICAO) AS DISTANCIA,
                I.VALOR, I.VALOR_PGTO, I.FORMAPGTO, I.IDPAGAMENTO, I.FLMAIL, I.IDINSCRICAO
            FROM ecmrun.INSCRICAO I, ecmrun.ATLETA A, 
            ecmrun.EVENTO E, ecmrun.EVENTO_MODALIDADE M
            WHERE M.IDITEM = I.IDITEM
            AND E.IDEVENTO = I.IDEVENTO
            AND A.IDATLETA = I.IDATLETA
            AND I.FLSTATUS = 'CONFIRMADO'
            AND I.IDPAGAMENTO = %s
        ''', (payment_id,))
        
        receipt_data = cur.fetchone()
        cur.close()

        if not receipt_data:
            app.logger.info("Dados não encontrados")
            return "Dados não encontrados", 404
        
        # Converter a data de string para datetime
        #data_pagamento = datetime.strptime(receipt_data[0], '%d/%m/%Y %H:%M')  # Formato correto

        # Estruturar os dados do comprovante
        receipt_data_dict = { 
            'data': receipt_data[0],  # Formatar data
            'evento': receipt_data[1],
            'endereco': receipt_data[2],
            'dataevento': receipt_data[3],
            'participante': receipt_data[4],
            'km': receipt_data[5],
            'valor': f'R$ {receipt_data[6]:,.2f}',  # Formatar valor
            'valortotal': f'R$ {receipt_data[7]:,.2f}',  # Formatar valor
            'formapgto': receipt_data[8],
            'inscricao': str(receipt_data[9]),
            'obs': 'Sua inscrição dá direito a: Número de peito, camiseta, viseira, sacolinha, e após concluir: medalha e troféu. Obs: Será apenas um troféu por equipe.'
        }
        
        app.logger.info("Dados da Inscrição:")
        app.logger.info(receipt_data)

        flmail = receipt_data[10]
        id_inscricao = receipt_data[11]
        app.logger.info(f' FLMAIL: { flmail }')
        app.logger.info(f' ID INSC: { id_inscricao }')


        if flmail == 'N':

            # Enviar email com os dados do comprovante
            send_email(receipt_data_dict)
        
            # Enviar notificação para o organizador
            send_organizer_notification(receipt_data_dict)

            cur1 = mysql.connection.cursor()
            cur1.execute('''
                UPDATE ecmrun.INSCRICAO SET FLMAIL = 'S'
                WHERE IDINSCRICAO = %s
            ''', (id_inscricao,))

            mysql.connection.commit()
            cur1.close()


        return render_template('comprovante_insc.html', **receipt_data_dict)

    except Exception as e:
        app.logger.error(f"Erro ao buscar dados do comprovante: {str(e)}")
        return "Erro ao buscar dados", 500

@app.route('/vercomprovante/<int:payment_id>')
def vercomprovante(payment_id):
    try:
        
        app.logger.info(f"Payment ID: {payment_id}")
        
        cur = mysql.connection.cursor()
        # Execute a SQL com o payment_id
        cur.execute('''
            SELECT I.DTPAGAMENTO, E.DESCRICAO, E.LOCAL, 
                CONCAT(E.DTINICIO,' ',E.HRINICIO,' - ',E.DTFIM) as DTEVENTO,
                CONCAT(A.NOME,' ',A.SOBRENOME) as NOME_COMPLETO, 
                CONCAT(M.DISTANCIA,' / ',M.DESCRICAO) AS DISTANCIA,
                I.VALOR, I.VALOR_PGTO, I.FORMAPGTO, I.IDPAGAMENTO, I.FLMAIL, I.IDINSCRICAO
            FROM ecmrun.INSCRICAO I, ecmrun.ATLETA A, 
            ecmrun.EVENTO E, ecmrun.EVENTO_MODALIDADE M
            WHERE M.IDITEM = I.IDITEM
            AND E.IDEVENTO = I.IDEVENTO
            AND A.IDATLETA = I.IDATLETA
            AND I.FLSTATUS = 'CONFIRMADO'
            AND I.IDPAGAMENTO = %s
        ''', (payment_id,))
        
        receipt_data = cur.fetchone()
        cur.close()

        if not receipt_data:
            app.logger.info("Dados não encontrados")
            return "Dados não encontrados", 404
        
        # Converter a data de string para datetime
        #data_pagamento = datetime.strptime(receipt_data[0], '%d/%m/%Y %H:%M:%S')  # Formato correto

        flmail = receipt_data[10]
        id_inscricao = receipt_data[11]
        app.logger.info(f' FLMAIL: { flmail }')
        app.logger.info(f' ID INSC: { id_inscricao }')

        # Estruturar os dados do comprovante
        receipt_data_dict = { 
            'data': receipt_data[0],  # Formatar data
            'evento': receipt_data[1],
            'endereco': receipt_data[2],
            'dataevento': receipt_data[3],
            'participante': receipt_data[4],
            'km': receipt_data[5],
            'valor': f'R$ {receipt_data[6]:,.2f}',  # Formatar valor
            'valortotal': f'R$ {receipt_data[7]:,.2f}',  # Formatar valor
            'formapgto': receipt_data[8],
            'inscricao': str(receipt_data[9]),
            'obs': 'Sua inscrição dá direito a: Número de peito, camiseta, viseira, sacolinha, e após concluir: medalha e troféu. Obs: Será apenas um troféu por equipe.'
        }
        
        app.logger.info("Dados da Inscrição:")
        app.logger.info(receipt_data)

        return render_template('vercomprovante.html', **receipt_data_dict)

    except Exception as e:
        app.logger.error(f"Erro ao buscar dados do comprovante: {str(e)}")
        return "Erro ao buscar dados", 500

@app.route('/comprovanteemail/<int:payment_id>')
def comprovanteemail(payment_id):
    try:
        
        app.logger.info(f"Payment ID: {payment_id}")
        
        cur = mysql.connection.cursor()
        # Execute a SQL com o payment_id
        cur.execute('''
            SELECT I.DTPAGAMENTO, E.DESCRICAO, E.LOCAL, 
                CONCAT(E.DTINICIO,' ',E.HRINICIO,' - ',E.DTFIM) as DTEVENTO,
                CONCAT(A.NOME,' ',A.SOBRENOME) as NOME_COMPLETO, 
                CONCAT(M.DISTANCIA,' / ',M.DESCRICAO) AS DISTANCIA,
                I.VALOR, I.VALOR_PGTO, I.FORMAPGTO, I.IDPAGAMENTO
            FROM ecmrun.INSCRICAO I, ecmrun.ATLETA A, 
            ecmrun.EVENTO E, ecmrun.EVENTO_MODALIDADE M
            WHERE M.IDITEM = I.IDITEM
            AND E.IDEVENTO = I.IDEVENTO
            AND A.IDATLETA = I.IDATLETA
            AND I.FLSTATUS = 'CONFIRMADO'
            AND I.IDPAGAMENTO = %s
        ''', (payment_id,))
        
        receipt_data = cur.fetchone()
        cur.close()

        if not receipt_data:
            app.logger.info("Dados não encontrados")
            return "Dados não encontrados", 404
        
        # Estruturar os dados do comprovante
        receipt_data_dict = { 
            'data': receipt_data[0],  # Formatar data
            'evento': receipt_data[1],
            'endereco': receipt_data[2],
            'dataevento': receipt_data[3],
            'participante': receipt_data[4],
            'km': receipt_data[5],
            'valor': f'R$ {receipt_data[6]:,.2f}',  # Formatar valor
            'valortotal': f'R$ {receipt_data[7]:,.2f}',  # Formatar valor
            'formapgto': receipt_data[8],
            'inscricao': str(receipt_data[9]),
            'obs': 'Sua inscrição dá direito a: Número de peito, camiseta, viseira, sacolinha, e após concluir: medalha e troféu. Obs: Será apenas um troféu por equipe.'
        }
        
        app.logger.info("Dados da Inscrição:")
        app.logger.error(receipt_data)

        return render_template('comprovante_email.html', **receipt_data_dict)

    except Exception as e:
        app.logger.error(f"Erro ao buscar dados do comprovante: {str(e)}")
        return "Erro ao buscar dados", 500



@app.route('/pagpix')
def pagpix():
    return render_template('pagpix.html')


@app.route('/get_evento_data')
def get_evento_data():
    try:
        cur = mysql.connection.cursor()
        cur.execute('''
            SELECT E.IDEVENTO, E.DESCRICAO, E.DTINICIO, E.DTFIM, E.HRINICIO,
                E.LOCAL, E.CIDADEUF, E.INICIO_INSCRICAO, E.FIM_INSCRICAO,
                M.IDITEM, M.DESCRICAO AS MODALIDADE, M.DISTANCIA, M.KM,
                M.VLINSCRICAO, M.VLMEIA, M.VLTAXA
            FROM ecmrun.EVENTO E, ecmrun.EVENTO_MODALIDADE M
            WHERE M.IDEVENTO = E.IDEVENTO
                AND E.IDEVENTO = 1
        ''')
        
        results = cur.fetchall()
        cur.close()
        
        if not results:
            return jsonify({'error': 'Evento não encontrado'}), 404
            
        # Estruturar os dados
        evento_data = {
            'idevento': results[0][0],
            'descricao': results[0][1],
            'dtinicio': results[0][2],
            'dtfim': results[0][3],
            'hrinicio': results[0][4],
            'local': results[0][5],
            'cidadeuf': results[0][6],
            'inicio_inscricao': results[0][7],
            'fim_inscricao': results[0][8],
            'iditem': results[0][9],
            'modalidades': results[0][10]
        }
        
        # Adicionar todas as modalidades
        for row in results:
            modalidade = {
                'iditem': row[9],
                'descricao': row[10],
                'distancia': row[11],
                'km': row[12],
                'vlinscricao': float(row[13]) if row[13] else 0,
                'vlmeia': float(row[14]) if row[14] else 0,
                'vltaxa': float(row[15]) if row[15] else 0
            }
            evento_data['modalidades'].append(modalidade)
            
        return jsonify(evento_data)
        
    except Exception as e:
        print(f"Erro ao buscar dados do evento: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/cupom200k')
def cupom200k():
    try:
        cur = mysql.connection.cursor()
        cur.execute('''
            SELECT E.IDEVENTO, E.DESCRICAO, E.DTINICIO, E.DTFIM, E.HRINICIO,
                E.LOCAL, E.CIDADEUF, E.INICIO_INSCRICAO, E.FIM_INSCRICAO,
                M.IDITEM, M.DESCRICAO AS MODALIDADE, M.DISTANCIA, M.KM,
                M.VLINSCRICAO, M.VLMEIA, M.VLTAXA, E.INICIO_INSCRICAO_EXT, E.FIM_INSCRICAO_EXT
            FROM ecmrun.EVENTO E, ecmrun.EVENTO_MODALIDADE M
            WHERE M.IDEVENTO = E.IDEVENTO
                AND E.IDEVENTO = 1
        ''')
        
        results = cur.fetchall()
        cur.close()
        
        if not results:
            return render_template('desafio200k.html', titulo="Evento não encontrado", modalidades=[])
            
        evento_titulo = results[0][1]  # DESCRICAO do evento
        modalidades = [{'id': row[9], 'descricao': row[10]} for row in results]
        vl200 = f'R$ {results[0][13]:,.2f}'
        vl100 = f'R$ {results[1][13]:,.2f}' 
        vl50 = f'R$ {results[2][13]:,.2f}'
        vl25 = f'R$ {results[3][13]:,.2f}'
        inicioinsc = results[0][16]
        fiminsc = results[0][17]        
        return render_template('cupom200k.html', titulo=evento_titulo, modalidades=modalidades,
                               vlSolo=vl200, vlDupla=vl100, vlQuarteto=vl50, vlOcteto=vl25, 
                               inicio_insc=inicioinsc, fim_insc=fiminsc)
        
    except Exception as e:
        print(f"Erro ao carregar página: {str(e)}")
        return render_template('desafio200k.html', titulo="Erro ao carregar evento", modalidades=[])


@app.route('/desafio200k')
def desafio200k():
    try:
        cur = mysql.connection.cursor()
        cur.execute('''
            SELECT E.IDEVENTO, E.DESCRICAO, E.DTINICIO, E.DTFIM, E.HRINICIO,
                E.LOCAL, E.CIDADEUF, E.INICIO_INSCRICAO, E.FIM_INSCRICAO,
                M.IDITEM, M.DESCRICAO AS MODALIDADE, M.DISTANCIA, M.KM,
                M.VLINSCRICAO, M.VLMEIA, M.VLTAXA, E.INICIO_INSCRICAO_EXT, E.FIM_INSCRICAO_EXT
            FROM ecmrun.EVENTO E, ecmrun.EVENTO_MODALIDADE M
            WHERE M.IDEVENTO = E.IDEVENTO
                AND E.IDEVENTO = 1
        ''')
        
        results = cur.fetchall()
        cur.close()
        
        if not results:
            return render_template('desafio200k.html', titulo="Evento não encontrado", modalidades=[])
            
        evento_titulo = results[0][1]  # DESCRICAO do evento
        dt_incio = results[0][2]     
        modalidades = [{'id': row[9], 'descricao': row[10]} for row in results]
        vl200 = f'R$ {results[0][13]:,.2f}'
        vl100 = f'R$ {results[1][13]:,.2f}' 
        vl50 = f'R$ {results[2][13]:,.2f}'
        vl25 = f'R$ {results[3][13]:,.2f}'
        inicioinsc = results[0][16]
        fiminsc = results[0][17]      
        dt_inicioinsc = results[0][7]
        dt_fiminsc = results[0][8]     
        
        #return render_template('desafio200k.html', titulo=evento_titulo, modalidades=modalidades, vlSolo=vl200, 
        #                       vlDupla=vl100, vlQuarteto=vl50, vlOcteto=vl25, inicio_insc=inicioinsc, fim_insc=fiminsc)

        return render_template('desafio200k.html', titulo=evento_titulo, modalidades=modalidades, vlSolo=vl200, 
                               vlDupla=vl100, vlQuarteto=vl50, vlOcteto=vl25, inicio_insc=inicioinsc, fim_insc=fiminsc, 
                               dt_inicio_insc=dt_inicioinsc, dt_fim_insc=dt_fiminsc, dt_inicio_evento=dt_incio)

    except Exception as e:
        print(f"Erro ao carregar página: {str(e)}")
        return render_template('desafio200k.html', titulo="Erro ao carregar evento", modalidades=[])


@app.route('/get_modalidade_valores/<int:iditem>')
def get_modalidade_valores(iditem):
    try:
        cur = mysql.connection.cursor()
        cur.execute('''
            SELECT VLINSCRICAO, VLTAXA 
            FROM ecmrun.EVENTO_MODALIDADE 
            WHERE IDITEM = %s
        ''', (iditem,))
        
        result = cur.fetchone()
        cur.close()        

        if result:
            vlinscricao = float(result[0]) if result[0] else 0
            vltaxa = float(result[1]) if result[1] else 0

            # Store in session
            session['cat_vlinscricao'] = vlinscricao
            session['cat_vltaxa'] = vltaxa
            session['cat_iditem'] = iditem
            
            return jsonify({
                'vlinscricao': vlinscricao,
                'vltaxa': vltaxa,
                'iditem': iditem
            })

        else:
            return jsonify({
                'success': False,
                'message': 'Usuário ou senha inválidos'
            }), 401


    except Exception as e:
        print(f"Erro ao buscar valores da modalidade: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/cadastro_atleta')
def cadastro_atleta():
    return render_template('cadastro_atleta.html')

@app.route('/autenticar', methods=['POST'])
def autenticar():
    email = request.form.get('email')
    cpf = request.form.get('cpf')
    categoria = request.form.get('categoria')

    verification_code = str(random.randint(1000, 9999))
    session['verification_code'] = verification_code
    
    return render_template('autenticar200k.html', verification_code=verification_code)

@app.route('/salvar-cadastro', methods=['POST'])
def salvar_cadastro():
    try:
        data = request.get_json()
        
        # Pegar a data no formato YYYY-MM-DD do campo input date
        data_nascimento_iso = data.get('data_nascimento')
        
        # Para o campo DATANASC (tipo DATE no banco de dados)
        # Não precisa de formatação adicional, o MySQL aceita o formato ISO YYYY-MM-DD
        
        # Para o campo DTNASCIMENTO (VARCHAR) - mantido por compatibilidade
        # Converter de YYYY-MM-DD para DD/MM/YYYY
        if data_nascimento_iso:
            date_parts = data_nascimento_iso.split('-')
            if len(date_parts) == 3:
                ano, mes, dia = date_parts
                data_nascimento_str = f"{dia}/{mes}/{ano}"  # Formato DD/MM/YYYY
            else:
                data_nascimento_str = ""  # caso haja algum problema com o formato
        else:
            data_nascimento_str = ""
        
        # Gerar data e hora atual no formato requerido
        data_cadastro = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Criptografar a senha usando SHA-256
        senha = data.get('senha')
        senha_hash = hashlib.sha256(senha.encode()).hexdigest()
        
        # Preparar query e parâmetros
        query = """
        INSERT INTO ecmrun.ATLETA (
            CPF, 
            NOME, 
            SOBRENOME, 
            DTNASCIMENTO, 
            DATANASC,
            NRCELULAR, 
            SEXO, 
            EMAIL, 
            TEL_EMERGENCIA, 
            CONT_EMERGENCIA, 
            SENHA, 
            ATIVO, 
            DTCADASTRO, 
            ESTADO, 
            ID_CIDADE
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        
        # Remover caracteres não numéricos do CPF e telefones
        cpf_limpo = re.sub(r'\D', '', data.get('cpf'))
        celular_limpo = re.sub(r'\D', '', data.get('celular'))
        tel_emergencia_limpo = re.sub(r'\D', '', data.get('telefone_emergencia')) if data.get('telefone_emergencia') else None
        
        params = (
            cpf_limpo,
            data.get('primeiro_nome').upper(),
            data.get('sobrenome').upper(),
            data_nascimento_str,                # Para o campo DTNASCIMENTO (string DD/MM/YYYY)
            data_nascimento_iso,                # Para o campo DATANASC (date YYYY-MM-DD)
            celular_limpo,
            data.get('sexo'),
            data.get('email'),
            tel_emergencia_limpo,
            data.get('contato_emergencia').upper() if data.get('contato_emergencia') else None,
            senha_hash,
            'S',  # ATIVO
            data_cadastro,
            data.get('estado'),
            data.get('cidade')
        )
        
        # Executar a query
        cur = mysql.connection.cursor()
        cur.execute(query, params)
        mysql.connection.commit()
        cur.close()
        
        return jsonify({
            'success': True,
            'message': 'Cadastro realizado com sucesso!'
        })
        
    except Exception as e:
        print(f"Erro ao salvar cadastro: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Erro ao realizar cadastro. Por favor, tente novamente.'
        }), 500


@app.route('/enviar-codigo-verificacao', methods=['POST'])
def enviar_codigo_verificacao():
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email não fornecido'}), 400

        # Gerar código de verificação
        verification_code = str(random.randint(1000, 9999))
        
        # Armazenar na sessão
        session['verification_code'] = verification_code
        session['verification_email'] = email
        
        # Simplificar o remetente
        #sender = 'ecmsistemasdeveloper@gmail.com'
        sender = "ECM RUN <ecmsistemasdeveloper@gmail.com>"

        # Criar mensagem com configuração mais simples
        msg = Message(
            'Código de Verificação - ECM Run',
            sender=sender,
            recipients=[email]
        )

        # Template HTML do email
        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #4376ac;">Verificação de Cadastro - ECM Run</h2>
            <p>Olá,</p>
            <p>Seu código de verificação é:</p>
            <h1 style="color: #4376ac; font-size: 32px; letter-spacing: 5px;">{verification_code}</h1>
            <p>Este código é válido por 10 minutos.</p>
            <p>Se você não solicitou este código, por favor ignore este email.</p>
            <br>
            <p>Atenciosamente,<br>Equipe ECM Run</p>
        </div>
        """

        # Adicionar logs para debug
        print(f'Tentando enviar email para: {email}')
        print(f'Código de verificação: {verification_code}')
        
        # Enviar email com tratamento de erro específico
        try:
            mail.send(msg)
            print('Email enviado com sucesso')
        except Exception as mail_error:
            print(f'Erro ao enviar email: {str(mail_error)}')
            return jsonify({
                'success': False,
                'message': f'Erro ao enviar email: {str(mail_error)}'
            }), 500

        return jsonify({
            'success': True,
            'message': 'Código de verificação enviado com sucesso'
        })
        
    except Exception as e:
        print(f"Erro geral na rota: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Erro ao processar requisição: {str(e)}'
        }), 500
    

@app.route('/verificar-codigo', methods=['POST'])
def verificar_codigo():
    try:
        data = request.get_json()
        codigo_informado = data.get('codigo')
        senha = data.get('senha')
        
        codigo_correto = session.get('verification_code')
        email = session.get('verification_email')
        
        if not codigo_correto or not email:
            return jsonify({
                'success': False,
                'message': 'Sessão expirada. Por favor, solicite um novo código.'
            }), 400
        
        if codigo_informado != codigo_correto:
            return jsonify({
                'success': False,
                'message': 'Código inválido'
            }), 400
            
        # Aqui você pode adicionar o código para salvar o usuário no banco de dados
        # com a senha criptografada
        
        # Limpar dados da sessão
        session.pop('verification_code', None)
        session.pop('verification_email', None)
        
        return jsonify({
            'success': True,
            'message': 'Código verificado com sucesso'
        })
        
    except Exception as e:
        print(f"Erro ao verificar código: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Erro ao verificar código'
        }), 500

# Email sending function
def send_verification_email(email, code):
    try:
        
        if not email:
            return jsonify({'success': False, 'message': 'Email não fornecido'}), 400

        # Gerar código de verificação
        #verification_code = str(random.randint(1000, 9999))
        
        # Armazenar na sessão
        session['code'] = code
        session['verif_email'] = email
        
        # Simplificar o remetente
        #sender = 'ecmsistemasdeveloper@gmail.com'
        sender = "ECM RUN <ecmsistemasdeveloper@gmail.com>"

        # Criar mensagem com configuração mais simples
        msg = Message(
            'Redefinição de Senha - ECM Run',
            sender=sender,
            recipients=[email]
        )

        # Template HTML do email
        msg.html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #4376ac;">Verificação de Cadastro - ECM Run</h2>
            <p>Olá,</p>
            <p>Seu código de verificação para redefinição de senha é::</p>
            <h1 style="color: #4376ac; font-size: 32px; letter-spacing: 5px;">{code}</h1>
            <p>Este código é válido por 10 minutos.</p>
            <p>Se você não solicitou este código, por favor ignore este email.</p>
            <br>
            <p>Atenciosamente,<br>Equipe ECM Run</p>
        </div>
        """

        # Adicionar logs para debug
        print(f'Tentando enviar email para: {email}')
        print(f'Código de verificação: {code}')
        
        # Enviar email com tratamento de erro específico
        try:
            mail.send(msg)
            print('Email enviado com sucesso')
        except Exception as mail_error:
            print(f'Erro ao enviar email: {str(mail_error)}')
            return jsonify({
                'success': False,
                'message': f'Erro ao enviar email: {str(mail_error)}'
            }), 500

        return jsonify({
            'success': True,
            'message': 'Código de verificação enviado com sucesso'
        })
        
    except Exception as e:
        print(f"Erro geral na rota: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Erro ao processar requisição: {str(e)}'
        }), 500


@app.route('/recuperar-senha', methods=['GET'])
def recuperar_senha():
    return render_template('recuperar_senha.html')

@app.route('/verificar-usuario', methods=['POST'])
def verificar_usuario():
    cpf_email = request.json.get('cpf_email')

    cur = mysql.connection.cursor()    
    if '@' in cpf_email:
        # Query for email
        cur.execute("""
            SELECT IDATLETA, EMAIL 
            FROM ATLETA
            WHERE EMAIL = %s OR CPF = %s
            """, (cpf_email, cpf_email))
    else:
        # Remove non-numeric characters from CPF
        cpf = ''.join(filter(str.isdigit, cpf_email))    
        cur.execute("""
            SELECT IDATLETA, EMAIL 
            FROM ATLETA
            WHERE EMAIL = %s OR CPF = %s
            """, (cpf, cpf))

    result = cur.fetchone()
    print(f'SQL: {result}')
        

    if result:
        # Generate verification code
        verification_code = str(random.randint(1000, 9999))
        
        # Store the code and user ID in session
        session['code'] = verification_code
        session['user_id'] = result[0]
        
        print(f'CODIGO: {verification_code}')
        print(f'IDATLETA: {result[0]}')
        
        # Send verification code via email
        if send_verification_email(result[1], verification_code):
            return jsonify({
                'success': True,
                'message': 'Código de verificação enviado para seu email.'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Erro ao enviar email. Tente novamente.'
            })
    
    return jsonify({
        'success': False,
        'message': 'Usuário não encontrado.'
    })

@app.route('/verificar-codigo2', methods=['POST'])
def verificar_codigo2():
    codigo = request.json.get('codigo')
    stored_code = session.get('code')
    print(f'CODIGO DIGITADO: {codigo}')
    print(f'STORED CODE:  {stored_code}')
    
    if codigo == stored_code:
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Código inválido.'})


@app.route('/alterar-senha', methods=['POST'])
def alterar_senha():
    nova_senha = request.json.get('senha')
    user_id = session.get('user_id')
    senha_hash = hashlib.sha256(nova_senha.encode()).hexdigest()
    
    if not user_id:
        return jsonify({
            'success': False,
            'message': 'Sessão expirada. Tente novamente.'
        })
        
    try:

        cur = mysql.connection.cursor()    
        cur.execute("""
            UPDATE ATLETA
            SET SENHA = %s 
            WHERE IDATLETA = %s
            """, (senha_hash, user_id))

        mysql.connection.commit()
        
        # Clear session
        session.pop('code', None)
        session.pop('user_id', None)
        
        return jsonify({
            'success': True,
            'message': 'Senha alterada com sucesso!'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Erro ao alterar senha. Tente novamente.'
        })
    finally:
        cur.close()

@app.route('/estados')
def estados():
    with open('static/json/estados.json', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/municipios')
def municipios():
    with open('static/json/municipios.json', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/inscricao200k')
def inscricao200k():
    return render_template('inscricao200k.html')

@app.route('/formulario200k')
def formulario200k():
    return render_template('formulario200k.html')

@app.route('/login')
def login():
    return render_template('login.html')

def validar_cpf(cpf):
    # Remove caracteres não numéricos
    cpf = ''.join(re.findall(r'\d', str(cpf)))
    
    # Verifica se o CPF tem 11 dígitos
    if len(cpf) != 11:
        return False
    
    # Verifica se todos os dígitos são iguais (ex: 111.111.111-11)
    if cpf == cpf[0] * 11:
        return False
    
    # Calcula o primeiro dígito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    primeiro_dv = 11 - (soma % 11)
    primeiro_dv = 0 if primeiro_dv >= 10 else primeiro_dv
    
    # Calcula o segundo dígito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    segundo_dv = 11 - (soma % 11)
    segundo_dv = 0 if segundo_dv >= 10 else segundo_dv
    
    # Verifica se os dígitos verificadores estão corretos
    return cpf[-2:] == f"{primeiro_dv}{segundo_dv}"


@app.route('/validar-cpf', methods=['GET'])
def validar_cpf_route():
    
    cpf = request.args.get('cpf', '')
    # Remove caracteres não numéricos
    cpf = ''.join(filter(str.isdigit, cpf))
    is_valid = validar_cpf(cpf)

    return jsonify({'valid': is_valid})

@app.route('/verificar-cpf', methods=['GET'])
def verificar_cpf_existente():
    cpf = request.args.get('cpf', '')
    # Remove caracteres não numéricos
    cpf = ''.join(filter(str.isdigit, cpf))
    

    try:
        cur = mysql.connection.cursor()
        cur.execute('SELECT IDATLETA FROM ecmrun.ATLETA WHERE CPF = %s', (cpf,))
        result = cur.fetchone()
        cur.close()
        
        return jsonify({'exists': bool(result)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def send_email(receipt_data):
    try:
        # Recuperar o email do atleta do banco de dados
        cur = mysql.connection.cursor()
        cur.execute('''
            SELECT A.EMAIL
            FROM ecmrun.ATLETA A
            JOIN ecmrun.INSCRICAO I ON I.IDATLETA = A.IDATLETA
            WHERE I.IDPAGAMENTO = %s
        ''', (receipt_data['inscricao'],))
        
        email_result = cur.fetchone()
        cur.close()

        if not email_result or not email_result[0]:
            app.logger.error("Email do atleta não encontrado")
            return False

        recipient_email = email_result[0]
        
        msg = Message(
            f'Comprovante de Inscrição - ID {receipt_data["inscricao"]}',
            sender=('ECM Run', 'ecmsistemasdeveloper@gmail.com'),
            recipients=[recipient_email]
        )
        
        msg.html = render_template('comprovante_email.html', **receipt_data)
        mail.send(msg)
        return True
        
    except Exception as e:
        app.logger.error(f"Erro ao enviar email: {str(e)}")
        return False


@app.route('/pesquisarCEP', methods=['GET'])
def pesquisar_cep():
    try:
        cep = request.args.get('cep', '').strip()
        
        # Remove caracteres não numéricos do CEP
        cep = ''.join(filter(str.isdigit, cep))
        
        if not cep or len(cep) != 8:
            return jsonify({'error': 'CEP inválido'}), 400
            
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT l.id_logradouro, l.CEP, upper(l.descricao) as descricao, l.UF, l.complemento, 
                   upper(l.descricao_sem_numero) as descricao_sem_numero, 
                   upper(l.descricao_cidade) as descricao_cidade,
                   upper(l.descricao_bairro) as descricao_bairro, upper(e.nome) as estado
            FROM ecmrun.logradouro l, ecmrun.estado e
            WHERE e.uf = l.UF AND l.CEP =  %s
        """, (cep,))
        
        result = cur.fetchone()
        cur.close()
        
        if result:
            return jsonify({
                'success': True,
                'data': {
                    'id_logradouro': result[0],
                    'cep': result[1],
                    'descricao': result[2],
                    'uf': result[3],
                    'complemento': result[4],
                    'descricao_sem_numero': result[5],
                    'descricao_cidade': result[6],
                    'descricao_bairro': result[7],
                    'estado': result[8]
                }
            })
        else:
            return jsonify({'success': False, 'message': 'CEP não encontrado'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/autenticar-login', methods=['POST'])
def autenticar_login():
    try:
        data = request.get_json()
        cpf_email = data.get('cpf_email')
        senha = data.get('senha')
        
        # Hash the password for comparison
        senha_hash = hashlib.sha256(senha.encode()).hexdigest()
        
        cur = mysql.connection.cursor()
        
        # Verifique se a entrada é e-mail ou CPF e consulte adequadamente
        if '@' in cpf_email:
            # Query for email
            cur.execute("""
                SELECT 
                    COALESCE(A.NOME, '') AS NOME, 
                    COALESCE(A.SOBRENOME, '') AS SOBRENOME, 
                    COALESCE(A.EMAIL, '') AS EMAIL, 
                    COALESCE(A.CPF, '') AS CPF, 
                    COALESCE(A.DTNASCIMENTO, '') AS DTNASCIMENTO, 
                    COALESCE(A.NRCELULAR, '') AS NRCELULAR, 
                    COALESCE(A.SEXO, '') AS SEXO, 
                    COALESCE(A.IDATLETA, '') AS IDATLETA, 
                    COALESCE(M.DESCRICAO, '') AS MODALIDADE, 
                    COALESCE(E.IDEVENTO, '') AS IDEVENTO, 
                    COALESCE(I.APOIO, '') AS APOIO, 
                    COALESCE(I.NOME_EQUIPE, '') AS NOME_EQUIPE,
                    COALESCE(I.INTEGRANTES, '') AS INTEGRANTES,
                    COALESCE(I.CAMISETA, '') AS CAMISETA,
                    COALESCE(I.VALOR, '') AS VALOR,
                    COALESCE(I.TAXA, '') AS TAXA,
                    COALESCE(I.VALOR_PGTO, '') AS VALOR_PGTO,
                    COALESCE(I.DTPAGAMENTO, '') AS DTPAGAMENTO,
                    COALESCE(I.FORMAPGTO, '') AS FORMAPGTO,
                    COALESCE(I.IDPAGAMENTO, '') AS IDPAGAMENTO,
                    COALESCE(E.DTINICIO, '') AS DTINICIO,
                    COALESCE(E.DESCRICAO, '') AS EVENTO,
                    COALESCE(CONCAT(E.DESCRICAO,' / ', M.DESCRICAO), '') AS EVENTO_MODAL,
                    COALESCE(I.FLSTATUS, '') AS FLSTATUS
                FROM ecmrun.ATLETA A
                LEFT JOIN ecmrun.INSCRICAO I ON I.IDATLETA = A.IDATLETA AND I.IDEVENTO = 1 AND I.FLSTATUS = 'CONFIRMADO'
                LEFT JOIN ecmrun.EVENTO E ON E.IDEVENTO = 1
                LEFT JOIN ecmrun.EVENTO_MODALIDADE M ON M.IDITEM = I.IDITEM AND I.IDATLETA IS NOT NULL
                WHERE A.EMAIL = %s AND A.SENHA = %s AND A.ATIVO = 'S'
            """, (cpf_email, senha_hash))
        else:
            # Remove non-numeric characters from CPF
            cpf = ''.join(filter(str.isdigit, cpf_email))
            cur.execute("""
                SELECT 
                    COALESCE(A.NOME, '') AS NOME, 
                    COALESCE(A.SOBRENOME, '') AS SOBRENOME, 
                    COALESCE(A.EMAIL, '') AS EMAIL, 
                    COALESCE(A.CPF, '') AS CPF, 
                    COALESCE(A.DTNASCIMENTO, '') AS DTNASCIMENTO, 
                    COALESCE(A.NRCELULAR, '') AS NRCELULAR, 
                    COALESCE(A.SEXO, '') AS SEXO, 
                    COALESCE(A.IDATLETA, '') AS IDATLETA, 
                    COALESCE(M.DESCRICAO, '') AS MODALIDADE, 
                    COALESCE(E.IDEVENTO, '') AS IDEVENTO, 
                    COALESCE(I.APOIO, '') AS APOIO, 
                    COALESCE(I.NOME_EQUIPE, '') AS NOME_EQUIPE,
                    COALESCE(I.INTEGRANTES, '') AS INTEGRANTES,
                    COALESCE(I.CAMISETA, '') AS CAMISETA,
                    COALESCE(I.VALOR, '') AS VALOR,
                    COALESCE(I.TAXA, '') AS TAXA,
                    COALESCE(I.VALOR_PGTO, '') AS VALOR_PGTO,
                    COALESCE(I.DTPAGAMENTO, '') AS DTPAGAMENTO,
                    COALESCE(I.FORMAPGTO, '') AS FORMAPGTO,
                    COALESCE(I.IDPAGAMENTO, '') AS IDPAGAMENTO,
                    COALESCE(E.DTINICIO, '') AS DTINICIO,
                    COALESCE(E.DESCRICAO, '') AS EVENTO,
                    COALESCE(CONCAT(E.DESCRICAO,' / ', M.DESCRICAO), '') AS EVENTO_MODAL,
                    COALESCE(I.FLSTATUS, '') AS FLSTATUS
                FROM ecmrun.ATLETA A
                LEFT JOIN ecmrun.INSCRICAO I ON I.IDATLETA = A.IDATLETA AND I.IDEVENTO = 1 AND I.FLSTATUS = 'CONFIRMADO'
                LEFT JOIN ecmrun.EVENTO E ON E.IDEVENTO = 1
                LEFT JOIN ecmrun.EVENTO_MODALIDADE M ON M.IDITEM = I.IDITEM AND I.IDATLETA IS NOT NULL
                WHERE A.CPF = %s AND A.SENHA = %s AND A.ATIVO = 'S'
            """, (cpf, senha_hash))
        
        result = cur.fetchone()
        cur.close()
        
        if result:
            nome_completo = f"{result[0]} {result[1]}"
            email = result[2]
            vcpf = result[3]
            dtnascimento = result[4]
            celular = result[5]
            sexo = result[6]
            idatleta = result[7]
            modalidade = result[8]
            apoio = result[10]
            equipe200 = result[11]
            integrantes = result[12]
            camiseta = result[13]
            valor = result[14]
            taxa = result[15]
            valortotal = result[16]
            dtpagamento = result[17]
            formapgto = result[18]
            idpagamento = result[19]
            dtinicio = result[20]
            evento = result[21]
            evento_modal = result[22]
            flstatus = result[23]
            
            # Converta as strings para objetos datetime
            dt_nascimento = datetime.strptime(dtnascimento, "%d/%m/%Y")
            dt_inicio = datetime.strptime(dtinicio, "%d/%m/%Y")

            # Calcule a idade
            idade = dt_inicio.year - dt_nascimento.year - ((dt_inicio.month, dt_inicio.day) < (dt_nascimento.month, dt_nascimento.day))
            app.logger.info(f'Idade: { idade }')
            app.logger.info(f'Data Evento: { dtinicio }')
                    
        
            # Store in session
            session['user_name'] = nome_completo
            session['user_email'] = email
            session['user_cpf'] = vcpf
            session['user_dtnascimento'] = dtnascimento
            session['user_dataevento'] = dtinicio
            session['user_idade'] = str(idade)
            session['user_celular'] = celular
            session['user_sexo'] = sexo
            session['user_idatleta'] = idatleta
            session['insc_modalidade'] = modalidade
            session['insc_apoio'] = apoio
            session['insc_equipe200'] = equipe200
            session['insc_integrantes'] = integrantes
            session['insc_camiseta'] = camiseta
            session['insc_valor'] = valor
            session['insc_taxa'] = taxa
            session['insc_valortotal'] = valortotal
            session['insc_dtpagamento'] = dtpagamento
            session['insc_formapgto'] = formapgto
            session['insc_idpagamento'] = idpagamento
            session['insc_evento'] = evento
            session['insc_evento_modal'] = evento_modal
            session['insc_flstatus'] = flstatus
            
            print(f'ID Pagamento: {idpagamento}')

            return jsonify({
                'success': True,
                'nome': nome_completo,
                'email': email,
                'cpf': vcpf,
                'dtnascimento': dtnascimento,
                'idade': str(idade),
                'celular': celular,
                'sexo': sexo,
                'idatleta': idatleta,
                'modalidade': modalidade,
                'apoio': apoio,
                'equipe200': equipe200,
                'integrantes': integrantes,
                'camiseta': camiseta,
                'valor': valor,
                'taxa': taxa,
                'valortotal': valortotal,
                'dtpagamento': dtpagamento,
                'formapgto': formapgto,
                'idpagamento': idpagamento,
                'dataevendo': dtinicio,
                'evento': evento,
                'evento_modal': evento_modal,
                'flstatus': flstatus
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Usuário ou senha inválidos'
            }), 401
            
    except Exception as e:
        print(f"Erro na autenticação: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Erro ao realizar autenticação'
        }), 500


@app.route('/check-user-session', methods=['POST'])
def check_user_session():
    try:
        data = request.get_json()
        user_email = data.get('email')
        user_cpf = data.get('cpf')
        
        if not (user_email or user_cpf):
            return jsonify({
                'success': False,
                'message': 'Dados de usuário não fornecidos'
            }), 400
        
        cur = mysql.connection.cursor()
        
        # Consulta usando e-mail ou CPF, dependendo do que foi fornecido
        if user_email:
            query_param = user_email
            where_clause = "A.EMAIL = %s"
        else:
            query_param = user_cpf
            where_clause = "A.CPF = %s"
        
        # Mesma consulta da rota de autenticação, mas sem verificar a senha
        cur.execute(f"""
            SELECT 
                COALESCE(A.NOME, '') AS NOME, 
                COALESCE(A.SOBRENOME, '') AS SOBRENOME, 
                COALESCE(A.EMAIL, '') AS EMAIL, 
                COALESCE(A.CPF, '') AS CPF, 
                COALESCE(A.DTNASCIMENTO, '') AS DTNASCIMENTO, 
                COALESCE(A.NRCELULAR, '') AS NRCELULAR, 
                COALESCE(A.SEXO, '') AS SEXO, 
                COALESCE(A.IDATLETA, '') AS IDATLETA, 
                COALESCE(M.DESCRICAO, '') AS MODALIDADE, 
                COALESCE(E.IDEVENTO, '') AS IDEVENTO, 
                COALESCE(I.APOIO, '') AS APOIO, 
                COALESCE(I.NOME_EQUIPE, '') AS NOME_EQUIPE,
                COALESCE(I.INTEGRANTES, '') AS INTEGRANTES,
                COALESCE(I.CAMISETA, '') AS CAMISETA,
                COALESCE(I.VALOR, '') AS VALOR,
                COALESCE(I.TAXA, '') AS TAXA,
                COALESCE(I.VALOR_PGTO, '') AS VALOR_PGTO,
                COALESCE(I.DTPAGAMENTO, '') AS DTPAGAMENTO,
                COALESCE(I.FORMAPGTO, '') AS FORMAPGTO,
                COALESCE(I.IDPAGAMENTO, '') AS IDPAGAMENTO,
                COALESCE(E.DTINICIO, '') AS DTINICIO,
                COALESCE(E.DESCRICAO, '') AS EVENTO,
                COALESCE(CONCAT(E.DESCRICAO,' / ', M.DESCRICAO), '') AS EVENTO_MODAL,
                COALESCE(I.FLSTATUS, '') AS FLSTATUS
            FROM ecmrun.ATLETA A
            LEFT JOIN ecmrun.INSCRICAO I ON I.IDATLETA = A.IDATLETA AND I.IDEVENTO = 1 AND I.FLSTATUS = 'CONFIRMADO'
            LEFT JOIN ecmrun.EVENTO E ON E.IDEVENTO = 1
            LEFT JOIN ecmrun.EVENTO_MODALIDADE M ON M.IDITEM = I.IDITEM AND I.IDATLETA IS NOT NULL
            WHERE {where_clause} AND A.ATIVO = 'S'
        """, (query_param,))
        
        result = cur.fetchone()
        cur.close()
        
        if result:
            nome_completo = f"{result[0]} {result[1]}"
            email = result[2]
            vcpf = result[3]
            dtnascimento = result[4]
            celular = result[5]
            sexo = result[6]
            idatleta = result[7]
            modalidade = result[8]
            apoio = result[10]
            equipe200 = result[11]
            integrantes = result[12]
            camiseta = result[13]
            valor = result[14]
            taxa = result[15]
            valortotal = result[16]
            dtpagamento = result[17]
            formapgto = result[18]
            idpagamento = result[19]
            dtinicio = result[20]
            evento = result[21]
            evento_modal = result[22]
            flstatus = result[23]
            
            # Converta as strings para objetos datetime
            dt_nascimento = datetime.strptime(dtnascimento, "%d/%m/%Y")
            dt_inicio = datetime.strptime(dtinicio, "%d/%m/%Y")

            # Calcule a idade
            idade = dt_inicio.year - dt_nascimento.year - ((dt_inicio.month, dt_inicio.day) < (dt_nascimento.month, dt_nascimento.day))

            print(result)    

            evento = result[21]
            print(f"Valor de EVENTO antes de retornar: {evento}")

            return jsonify({
                'success': True,
                'nome': nome_completo,
                'email': email,
                'cpf': vcpf,
                'dtnascimento': dtnascimento,
                'idade': str(idade),
                'celular': celular,
                'sexo': sexo,
                'idatleta': idatleta,
                'modalidade': modalidade,
                'apoio': apoio,
                'equipe200': equipe200,
                'integrantes': integrantes,
                'camiseta': camiseta,
                'valor': valor,
                'taxa': taxa,
                'valortotal': valortotal,
                'dtpagamento': dtpagamento,
                'formapgto': formapgto,
                'idpagamento': idpagamento,
                'dataevento': dtinicio,
                'evento': evento,
                'evento_modal': evento_modal,
                'flstatus': flstatus
            })
            
        else:
            # Usuário não encontrado ou inativo
            return jsonify({
                'success': False,
                'message': 'Usuário não encontrado ou inativo'
            }), 404
            
    except Exception as e:
        print(f"Erro ao verificar sessão do usuário: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Erro ao verificar sessão do usuário'
        }), 500


@app.route('/pagamento')
def pagamento():
    # Get values from session
    vlinscricao = session.get('valoratual', 0)
    vltaxa = session.get('valortaxa', 0)
    valor_total = float(vlinscricao) + float(vltaxa)
    
    return render_template('pagamento.html', 
                         valor_inscricao=vlinscricao,
                         valor_taxa=vltaxa,
                         valor_total=valor_total)


@app.route('/gerar-pix', methods=['POST'])
def gerar_pix():
    try:
        data = request.get_json()
        # Add more robust validation and logging
        print(f"Raw data received: {data}")
        
        # More robust parsing with better error handling
        try:
            valor_total = round(float(data.get('valor_total', 0)), 2)
            valor_atual = round(float(data.get('valor_atual', 0)), 2)
            valor_taxa = round(float(data.get('valor_taxa', 0)), 2)
        except (ValueError, TypeError) as e:
            print(f"Error parsing values: {str(e)}")
            print(f"valor_total: {data.get('valor_total')}, type: {type(data.get('valor_total'))}")
            print(f"valor_atual: {data.get('valor_atual')}, type: {type(data.get('valor_atual'))}")
            print(f"valor_taxa: {data.get('valor_taxa')}, type: {type(data.get('valor_taxa'))}")
            
            # Try to convert from string with comma to float
            try:
                valor_total = round(float(str(data.get('valor_total', '0')).replace(',', '.')), 2)
                valor_atual = round(float(str(data.get('valor_atual', '0')).replace(',', '.')), 2)
                valor_taxa = round(float(str(data.get('valor_taxa', '0')).replace(',', '.')), 2)
                print(f"After conversion: valor_total={valor_total}, valor_atual={valor_atual}, valor_taxa={valor_taxa}")
            except Exception as conversion_error:
                print(f"Conversion attempt failed: {str(conversion_error)}")
                return jsonify({
                    'success': False,
                    'message': 'Erro ao processar valores. Verifique se os valores são numéricos válidos.'
                }), 400
        
        camisa = data.get('camiseta')
        apoio = data.get('apoio')
        equipe = data.get('equipe')
        equipe200 = data.get('nome_equipe')
        integrantes = data.get('integrantes')
        idatleta = data.get('idatleta')

        # Store in session
        session['valorTotal'] = valor_total
        session['valorAtual'] = valor_atual
        session['valorTaxa'] = valor_taxa
        session['formaPagto'] = 'PIX'
        session['Camisa'] = camisa
        session['Equipe'] = equipe
        session['Apoio'] = apoio
        session['Equipe200'] = equipe200
        session['Integrantes'] = integrantes
        session['idAtleta'] = idatleta
        
        # Validate minimum transaction amount
        if valor_total < 1:
            return jsonify({
                'success': False,
                'message': 'Valor mínimo da transação deve ser maior que R$ 1,00'
            }), 400
        
        print("=== DEBUG: Iniciando geração do PIX ===")
        print(f"Valor total processado: {valor_total}")
        print(f"Valor atual: {valor_atual}")
        print(f"Valor taxa: {valor_taxa}")
        
        # Get payer info and validate it's present
        email = session.get('user_email')
        nome_completo = session.get('user_name', '')
        
        # Fallback to data from request if session is empty
        if not email:
            email = data.get('email')
            print(f"Email not found in session, using from request: {email}")
        
        if not nome_completo:
            nome_completo = data.get('nome', '')
            print(f"Nome not found in session, using from request: {nome_completo}")
            
        nome_parts = nome_completo.split() if nome_completo else ['', '']
        
        cpf = session.get('user_cpf')
        if not cpf:
            cpf = data.get('cpf')
            print(f"CPF not found in session, using from request: {cpf}")
            
        # Validate required fields
        if not email:
            return jsonify({
                'success': False,
                'message': 'Email do pagador é obrigatório'
            }), 400
            
        if not cpf:
            return jsonify({
                'success': False,
                'message': 'CPF do pagador é obrigatório'
            }), 400
            
        # Clean CPF format
        cpf_cleaned = re.sub(r'\D', '', cpf) if cpf else ""
        session['CPF'] = cpf_cleaned

        print(f"Dados do pagador finais:")
        print(f"- Email: {email}")
        print(f"- Nome: {nome_completo}")
        print(f"- CPF: {cpf_cleaned}")

        # Try to call email function safely
        try:
            fn_email(email)
        except Exception as email_error:
            print(f"Warning: Error in fn_email: {str(email_error)}")
            # Continue processing even if email function fails

        # Generate unique reference
        external_reference = str(uuid.uuid4())

        preference_data = {
            "items": [{
                "id": "desafio200k_inscricao",
                "title": "Inscrição Desafio 200k",
                "description": "Inscrição para o 4º Desafio 200k",
                "category_id": "sports_tickets",
                "quantity": 1,
                "unit_price": valor_total
            }],
            "statement_descriptor": "DESAFIO200K"
        }
        
        preference_result = sdk.preference().create(preference_data)

        # Create payment data
        payment_data = {
            "transaction_amount": float(valor_total),  # Ensure it's a float
            "description": "Inscrição 4º Desafio 200k",
            "payment_method_id": "pix",
            "payer": {
                "email": email,
                "first_name": nome_parts[0] if nome_parts else "",
                "last_name": " ".join(nome_parts[1:]) if len(nome_parts) > 1 else "",
                "identification": {
                    "type": "CPF",
                    "number": cpf_cleaned
                }   
            },
            "notification_url": "https://ecmrun.com.br/webhook",
            "external_reference": external_reference
        }
        
        print("Dados do pagamento preparados:")
        print(json.dumps(payment_data, indent=2))

        # Create payment in Mercado Pago
        print("Enviando requisição para o Mercado Pago...")
        
        try:
            payment_response = sdk.payment().create(payment_data)
        except Exception as mp_error:
            print(f"Erro na comunicação com Mercado Pago: {str(mp_error)}")
            return jsonify({
                'success': False,
                'message': f'Erro na comunicação com o gateway de pagamento: {str(mp_error)}'
            }), 500
        
        print("Resposta do Mercado Pago recebida")
        
        # Validate response structure
        if not payment_response:
            print("Erro: Resposta vazia do Mercado Pago")
            return jsonify({
                'success': False,
                'message': 'Resposta vazia do gateway de pagamento'
            }), 500
            
        if "response" not in payment_response:
            print(f"Erro: Formato de resposta inesperado: {payment_response}")
            return jsonify({
                'success': False,
                'message': 'Formato de resposta inesperado do gateway de pagamento'
            }), 500

        payment = payment_response["response"]
        
        # Check for error in response
        if "error" in payment:
            print(f"Erro retornado pelo Mercado Pago: {payment}")
            return jsonify({
                'success': False,
                'message': f'Erro do gateway de pagamento: {payment.get("message", "Erro desconhecido")}'
            }), 400
        
        # Check for QR code data
        if "point_of_interaction" not in payment:
            print("Erro: point_of_interaction não encontrado na resposta")
            print(f"Resposta completa: {json.dumps(payment, indent=2)}")
            return jsonify({
                'success': False,
                'message': 'Dados do PIX não disponíveis'
            }), 500
            
        if "transaction_data" not in payment["point_of_interaction"]:
            print("Erro: transaction_data não encontrado em point_of_interaction")
            return jsonify({
                'success': False,
                'message': 'Dados do QR code não disponíveis'
            }), 500

        # Extract QR code data
        qr_code = payment['point_of_interaction']['transaction_data'].get('qr_code', '')
        qr_code_base64 = payment['point_of_interaction']['transaction_data'].get('qr_code_base64', '')
        payment_id = payment.get('id', '')
        
        if not qr_code or not qr_code_base64 or not payment_id:
            print("Erro: Dados do PIX incompletos")
            return jsonify({
                'success': False,
                'message': 'Dados do PIX incompletos'
            }), 500

        # Success response
        return jsonify({
            'success': True,
            'qr_code': qr_code,
            'qr_code_base64': qr_code_base64,
            'payment_id': payment_id
        })

    except Exception as e:
        print(f"=== ERRO CRÍTICO: ===")
        print(f"Tipo do erro: {type(e)}")
        print(f"Mensagem de erro: {str(e)}")
        print(f"Stack trace:")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'message': f'Erro ao gerar PIX: {str(e)}'
        }), 500


@app.route('/recuperar-qrcode/<payment_id>', methods=['GET'])
def recuperar_qrcode(payment_id):
    try:
        # Recupera o pagamento do Mercado Pago
        payment = sdk.payment().get(payment_id)
        if payment['status'] == 404:
            return jsonify({'success': False, 'message': 'Pagamento não encontrado'})
            
        # Extrai os dados do QR code
        point_of_interaction = payment.get('point_of_interaction', {})
        transaction_data = point_of_interaction.get('transaction_data', {})
        
        return jsonify({
            'success': True,
            'qr_code': transaction_data.get('qr_code'),
            'qr_code_base64': transaction_data.get('qr_code_base64')
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    

# @app.route('/verificar-pagamento/<payment_id>')
# def verificar_pagamento(payment_id):
#     try:
#         # Buscar o status diretamente do Mercado Pago
#         payment_response = sdk.payment().get(payment_id)
#         payment = payment_response["response"]

#         print(f"Status do pagamento recebido: {payment['status']}")
        
#         if payment["status"] == "approved":
#             # Verificar se já não foi processado antes
#             cur = mysql.connection.cursor()
#             cur.execute("SELECT * FROM ecmrun.INSCRICAO WHERE IDPAGAMENTO = %s", (payment_id,))
#             existing_record = cur.fetchone()
            
#             if not existing_record:
#                 # Calculate valor_pgto (total payment)
#                 valor = float(session.get('valorAtual', 0))
#                 taxa = float(session.get('valorTaxa', 0))
#                 valoratual = valor + taxa
#                 valor_pgto = float(session.get('valorTotal', 0))
#                 desconto = valoratual - valor_pgto
#                 formaPagto = session.get('formaPagto')
#                 camiseta = session.get('Camisa')
#                 equipe = session.get('Equipe')
#                 apoio = session.get('Apoio')
#                 equipe200 = session.get('Equipe200')
#                 integrantes = session.get('Integrantes')

#                 data_e_hora_atual = datetime.now()
#                 fuso_horario = timezone('America/Manaus')
#                 data_e_hora_manaus = data_e_hora_atual.astimezone(fuso_horario)
#                 data_pagamento = data_e_hora_manaus.strftime('%d/%m/%Y %H:%M')
                                
#                 # Get additional data from session
#                 idatleta = session.get('idAtleta')
#                 cpf = session.get('CPF')

                
#                 # Insert payment record
#                 query = """
#                 INSERT INTO ecmrun.INSCRICAO (
#                     IDATLETA, CPF, IDEVENTO, IDITEM, CAMISETA, APOIO, 
#                     NOME_EQUIPE, INTEGRANTES, VALOR, TAXA, DESCONTO,
#                     VALOR_PGTO, DTPAGAMENTO, FLSTATUS, FORMAPGTO, 
#                     IDPAGAMENTO, FLMAIL, EQUIPE
#                 ) VALUES (
#                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
#                 )
#                 """
                
#                 params = (
#                     idatleta,                            # IDATLETA
#                     cpf,                                 # CPF
#                     1,                                   # IDEVENTO (hardcoded as 1 for this event)
#                     session.get('cat_iditem'),           # IDITEM
#                     camiseta,                            # CAMISETA
#                     apoio,                               # APOIO
#                     equipe200,                           # NOME_EQUIPE
#                     integrantes,                         # INTEGRANTES
#                     valor,                               # VALOR
#                     taxa,                                # TAXA
#                     desconto,                            # DESCONTO
#                     valor_pgto,                          # VALOR_PGTO
#                     data_pagamento,                      # DTPAGAMENTO
#                     'CONFIRMADO',                        # FLSTATUS
#                     formaPagto,                          # FORMAPGTO
#                     payment_id,                          # IDPAGAMENTO
#                     'N',
#                     equipe
#                 )
                
#                 cur.execute(query, params)
#                 mysql.connection.commit()
#                 cur.close()
                
#                 print("Registro de pagamento inserido com sucesso!")
                
#                 return jsonify({
#                     'success': True,
#                     'status': 'approved',
#                     'message': 'Pagamento processado e registrado'
#                 })
#             else:
#                 print("Pagamento já processado anteriormente")
#                 return jsonify({
#                     'success': True,
#                     'status': 'approved',
#                     'message': 'Pagamento já processado'
#                 })
        
#         return jsonify({
#             'success': True,
#             'status': payment["status"]
#         })
        
#     except Exception as e:
#         print(f"Erro ao verificar pagamento: {str(e)}")
#         # Ensure JSON is returned even on error
#         return jsonify({
#             'success': False, 
#             'message': str(e),
#             'status': 'error'
#         }), 500
    

@app.route('/verificar-pagamento/<payment_id>')
def verificar_pagamento(payment_id):
    try:
        # Buscar o status diretamente do Mercado Pago
        payment_response = sdk.payment().get(payment_id)
        payment = payment_response["response"]

        print(f"Status do pagamento recebido: {payment['status']}")
        
        if payment["status"] == "approved":

            data_e_hora_atual = datetime.now()
            fuso_horario = timezone('America/Manaus')
            data_e_hora_manaus = data_e_hora_atual.astimezone(fuso_horario)
            data_pagamento = data_e_hora_manaus.strftime('%d/%m/%Y %H:%M')


            # Verificar se já não foi processado antes
            cur = mysql.connection.cursor()
            cur.execute("SELECT IDINSCRICAO FROM INSCRICAO WHERE IDPAGAMENTO = %s", (payment_id,))
            existing_record = cur.fetchone()
            
            if existing_record:

                cur.execute("""
                    UPDATE INSCRICAO SET
                        DTPAGAMENTO = %s,
                        FLSTATUS = %s  
                    WHERE IDINSCRICAO = %s
                    """, (
                        data_pagamento,         
                        'CONFIRMADO',           
                        existing_record[0]      

                ))

                mysql.connection.commit()
                cur.close()

                return jsonify({
                    'success': True,
                    'status': 'approved',
                    'message': 'Pagamento processado e registrado'
                })

            else:

                # Calculate valor_pgto (total payment)
                valor = float(session.get('valorAtual', 0))
                taxa = float(session.get('valorTaxa', 0))
                valoratual = valor + taxa
                valor_pgto = float(session.get('valorTotal', 0))
                desconto = valoratual - valor_pgto
                formaPagto = session.get('formaPagto')
                camiseta = session.get('Camisa')
                equipe = session.get('Equipe')
                apoio = session.get('Apoio')
                equipe200 = session.get('Equipe200')
                integrantes = session.get('Integrantes')
                                
                # Get additional data from session
                #idatleta = session.get('user_idatleta')
                #cpf = session.get('user_cpf')

                idatleta = session.get('idAtleta')
                cpf = session.get('CPF')
                
                # Insert payment record
                query = """
                INSERT INTO INSCRICAO (
                    IDATLETA, CPF, IDEVENTO, IDITEM, CAMISETA, APOIO, 
                    NOME_EQUIPE, INTEGRANTES, VALOR, TAXA, DESCONTO,
                    VALOR_PGTO, DTPAGAMENTO, FLSTATUS, FORMAPGTO, 
                    IDPAGAMENTO, FLMAIL, EQUIPE
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """
                
                params = (
                    idatleta,                    # IDATLETA
                    cpf,                         # CPF
                    1,                           # IDEVENTO (hardcoded as 1 for this event)
                    session.get('cat_iditem'),   # IDITEM
                    camiseta,                    # CAMISETA
                    apoio,                       # APOIO
                    equipe200,                   # NOME_EQUIPE
                    integrantes,                 # INTEGRANTES
                    valor,                       # VALOR
                    taxa,                        # TAXA
                    desconto,                    # DESCONTO
                    valor_pgto,                  # VALOR_PGTO
                    data_pagamento,              # DTPAGAMENTO
                    'CONFIRMADO',                # FLSTATUS
                    formaPagto,                  # FORMAPGTO
                    payment_id,                  # IDPAGAMENTO
                    'N',
                    equipe
                )
                
                cur.execute(query, params)
                mysql.connection.commit()
                cur.close()
                
                print("Registro de pagamento inserido com sucesso!")
                
                return jsonify({
                    'success': True,
                    'status': 'approved',
                    'message': 'Pagamento processado e registrado'
                })
                    
        return jsonify({
            'success': True,
            'status': payment["status"]
        })
        
    except Exception as e:
        print(f"Erro ao verificar pagamento: {str(e)}")
        # Ensure JSON is returned even on error
        return jsonify({
            'success': False, 
            'message': str(e),
            'status': 'error'
        }), 500


@app.route('/inscricao-temp/<cpf>', methods=['POST'])
def inscricao_temp(cpf):
    try:
        # Obter dados do request JSON em vez de session
        data = request.json
        # Usar dados do request JSON
        valor = float(data.get('valor_atual', 0))
        taxa = float(data.get('valor_taxa', 0))
        valoratual = valor + taxa
        valor_pgto = float(data.get('valor_total', 0))
        desconto = valoratual - valor_pgto
        
        formaPagto = data.get('forma_pagto', 'PIX')
        camiseta = data.get('camiseta')
        equipe = data.get('equipe')
        apoio = data.get('apoio')
        equipe200 = data.get('equipe_nome')
        integrantes = data.get('integrantes')
        idpagamento = data.get('payment_id')
        cat_iditem = data.get('cat_iditem')
        
        data_e_hora_atual = datetime.now()
        fuso_horario = timezone('America/Manaus')
        data_e_hora_manaus = data_e_hora_atual.astimezone(fuso_horario)
        data_pagamento = data_e_hora_manaus.strftime('%d/%m/%Y %H:%M')

        cur = mysql.connection.cursor()
        cur.execute("SELECT IDINSCRICAO FROM INSCRICAO WHERE FLSTATUS = 'PENDENTE' AND CPF = %s AND IDEVENTO = 1", (cpf,))
        existing_record = cur.fetchone()
        
        if existing_record:
            cur = mysql.connection.cursor()

            cur.execute("""
                UPDATE INSCRICAO 
                SET IDITEM = %s, 
                    CAMISETA = %s,
                    APOIO = %s,
                    NOME_EQUIPE = %s, 
                    INTEGRANTES = %s,
                    VALOR = %s,
                    TAXA = %s,
                    DESCONTO = %s,
                    VALOR_PGTO = %s,
                    DTPAGAMENTO = %s,
                    FLSTATUS = %s,
                    FORMAPGTO = %s,
                    IDPAGAMENTO = %s,
                    FLMAIL = %s,
                    EQUIPE = %s,  
                WHERE IDINSCRICAO = %s
                """, (
                    cat_iditem,                 # IDITEM
                    camiseta,                   # CAMISETA
                    apoio,                      # APOIO
                    equipe200,                  # NOME_EQUIPE
                    integrantes,                # INTEGRANTES
                    valor,                      # VALOR
                    taxa,                       # TAXA
                    desconto,                   # DESCONTO
                    valor_pgto,                 # VALOR_PGTO
                    data_pagamento,             # DTPAGAMENTO
                    'PENDENTE',                 # FLSTATUS
                    formaPagto,                 # FORMAPGTO
                    idpagamento,                # IDPAGAMENTO
                    'N',                        # FLMAIL
                    equipe,                     # EQUIPE
                    existing_record[0]          # IDINSCRICAO

            ))
            mysql.connection.commit()
            cur.close()
        
        else:

            # Obter idatleta do banco baseado no CPF
            cur = mysql.connection.cursor()
            cur.execute("SELECT IDATLETA FROM ecmrun.ATLETA WHERE CPF = %s", (cpf,))
            atleta_record = cur.fetchone()
            
            if atleta_record:
                idatleta = atleta_record[0]
            else:
                idatleta = None
        
            # Insert payment record
            query = """
            INSERT INTO INSCRICAO (
                IDATLETA, CPF, IDEVENTO, IDITEM, CAMISETA, APOIO, 
                NOME_EQUIPE, INTEGRANTES, VALOR, TAXA, DESCONTO,
                VALOR_PGTO, DTPAGAMENTO, FLSTATUS, FORMAPGTO, 
                IDPAGAMENTO, FLMAIL, EQUIPE
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """
            
            params = (
                idatleta,                   # IDATLETA
                cpf,                        # CPF
                1,                          # IDEVENTO (hardcoded as 1 for this event)
                cat_iditem,                 # IDITEM
                camiseta,                   # CAMISETA
                apoio,                      # APOIO
                equipe200,                  # NOME_EQUIPE
                integrantes,                # INTEGRANTES
                valor,                      # VALOR
                taxa,                       # TAXA
                desconto,                   # DESCONTO
                valor_pgto,                 # VALOR_PGTO
                data_pagamento,             # DTPAGAMENTO
                'PENDENTE',                 # FLSTATUS
                formaPagto,                 # FORMAPGTO
                idpagamento,                # IDPAGAMENTO
                'N',                        # FLMAIL
                equipe                      # EQUIPE
            )
            
            cur.execute(query, params)
            mysql.connection.commit()
            cur.close()
        
        print(f"Pré-inscrição inserida com sucesso para CPF {cpf} com payment_id {idpagamento}!")
        
        return jsonify({
            'success': True,
            'status': 'inserido',
            'message': 'registrado'
        })
        
    except Exception as e:
        print(f"Erro ao lançar pré-inscrição: {str(e)}")
        # Ensure JSON is returned even on error
        return jsonify({
            'success': False, 
            'message': str(e),
            'status': 'error'
        }), 500

@app.route('/inscricao-cartao/<cpf>', methods=['POST'])
def inscricao_cartao(cpf):
    try:
        # Obter dados do request JSON em vez de session
        data = request.json
        # Usar dados do request JSON
        valor = float(data.get('valor_atual', 0))
        taxa = float(data.get('valor_taxa', 0))
        valoratual = valor + taxa
        valor_pgto = float(data.get('valor_total', 0))
        desconto = valoratual - valor_pgto
        
        #formaPagto = data.get('forma_pagto', 'PIX')
        formaPagto = data.get('forma_pagto')
        camiseta = data.get('camiseta')
        equipe = data.get('equipe')
        apoio = data.get('apoio')
        equipe200 = data.get('equipe_nome')
        integrantes = data.get('integrantes')
        idpagamento = data.get('payment_id')
        cat_iditem = data.get('cat_iditem')
        
        data_e_hora_atual = datetime.now()
        fuso_horario = timezone('America/Manaus')
        data_e_hora_manaus = data_e_hora_atual.astimezone(fuso_horario)
        data_pagamento = data_e_hora_manaus.strftime('%d/%m/%Y %H:%M')

        cur = mysql.connection.cursor()
        cur.execute("SELECT IDINSCRICAO FROM INSCRICAO WHERE CPF = %s AND IDEVENTO = 1", (cpf,))
        existing_record = cur.fetchone()
        
        if existing_record:
            cur = mysql.connection.cursor()

            cur.execute("""
                UPDATE INSCRICAO 
                SET IDITEM = %s, 
                    CAMISETA = %s,
                    APOIO = %s,
                    NOME_EQUIPE = %s, 
                    INTEGRANTES = %s,
                    VALOR = %s,
                    TAXA = %s,
                    DESCONTO = %s,
                    VALOR_PGTO = %s,
                    DTPAGAMENTO = %s,
                    FLSTATUS = %s,
                    FORMAPGTO = %s,
                    IDPAGAMENTO = %s,
                    FLMAIL = %s,
                    EQUIPE = %s,  
                WHERE IDINSCRICAO = %s
                """, (
                    cat_iditem,                 # IDITEM
                    camiseta,                   # CAMISETA
                    apoio,                      # APOIO
                    equipe200,                  # NOME_EQUIPE
                    integrantes,                # INTEGRANTES
                    valor,                      # VALOR
                    taxa,                       # TAXA
                    desconto,                   # DESCONTO
                    valor_pgto,                 # VALOR_PGTO
                    data_pagamento,             # DTPAGAMENTO
                    'CONFIRMADO',               # FLSTATUS
                    formaPagto,                 # FORMAPGTO
                    idpagamento,                # IDPAGAMENTO
                    'N',                        # FLMAIL
                    equipe,                     # EQUIPE
                    existing_record[0]          # IDINSCRICAO

            ))
            mysql.connection.commit()
            cur.close()
        
        else:

            # Obter idatleta do banco baseado no CPF
            cur = mysql.connection.cursor()
            cur.execute("SELECT IDATLETA FROM ecmrun.ATLETA WHERE CPF = %s", (cpf,))
            atleta_record = cur.fetchone()
            
            if atleta_record:
                idatleta = atleta_record[0]
            else:
                idatleta = None
        
            # Insert payment record
            query = """
            INSERT INTO INSCRICAO (
                IDATLETA, CPF, IDEVENTO, IDITEM, CAMISETA, APOIO, 
                NOME_EQUIPE, INTEGRANTES, VALOR, TAXA, DESCONTO,
                VALOR_PGTO, DTPAGAMENTO, FLSTATUS, FORMAPGTO, 
                IDPAGAMENTO, FLMAIL, EQUIPE
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """
            
            params = (
                idatleta,                   # IDATLETA
                cpf,                        # CPF
                1,                          # IDEVENTO (hardcoded as 1 for this event)
                cat_iditem,                 # IDITEM
                camiseta,                   # CAMISETA
                apoio,                      # APOIO
                equipe200,                  # NOME_EQUIPE
                integrantes,                # INTEGRANTES
                valor,                      # VALOR
                taxa,                       # TAXA
                desconto,                   # DESCONTO
                valor_pgto,                 # VALOR_PGTO
                data_pagamento,             # DTPAGAMENTO
                'CONFIRMADO',               # FLSTATUS
                formaPagto,                 # FORMAPGTO
                idpagamento,                # IDPAGAMENTO
                'N',                        # FLMAIL
                equipe                      # EQUIPE
            )
            
            cur.execute(query, params)
            mysql.connection.commit()
            cur.close()
        
        print(f"inscrição inserida com sucesso para CPF {cpf} com payment_id {idpagamento}!")
        
        return jsonify({
            'success': True,
            'status': 'inserido',
            'message': 'registrado'
        })
        
    except Exception as e:
        print(f"Erro ao lançar pré-inscrição: {str(e)}")
        # Ensure JSON is returned even on error
        return jsonify({
            'success': False, 
            'message': str(e),
            'status': 'error'
        }), 500


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    app.logger.info(f"Webhook received: {data}")
    
    if data['type'] == 'payment':
        payment_info = sdk.payment().get(data['data']['id'])
        app.logger.info(f"Payment info: {payment_info}")
    
    return jsonify({'status': 'ok'}), 200


@app.route('/criar_preferencia', methods=['POST'])
def criar_preferencia():

    app.logger.info("Recebendo requisição para criar preferência")
    app.logger.debug(f"Dados recebidos: {request.get_json()}")
    app.logger.debug(f"MP_ACCESS_TOKEN configurado: {'MP_ACCESS_TOKEN' in os.environ}")

    try:
        data = request.get_json()
        
        # Log dos dados recebidos
        print("Dados recebidos:", data)
        
        # Get values from localStorage (sent in request)
        valor_total = float(data.get('valortotal', 0))
        valor_taxa = float(data.get('valortaxa', 0))
        nome_completo = data.get('user_name', '')
        
        # Split full name into first and last name
        nome_parts = nome_completo.split(' ', 1)
        first_name = nome_parts[0]
        last_name = nome_parts[1] if len(nome_parts) > 1 else ''
        
        preco_final = valor_total
        
        print("Preço final calculado:", preco_final)
        
        # Configurar URLs de retorno
        base_url = request.url_root.rstrip('/')  # Remove trailing slash if present

        back_urls = {
            "success": f"{base_url}/aprovado",
            "failure": f"{base_url}/negado",
            "pending": f"{base_url}/negado"
        }

        preference_data = {
            "items": [
                {
                    "id": "200k-inscricao",
                    "title": "Inscrição 4º Desafio 200k",
                    "quantity": 1,
                    "unit_price": float(preco_final),
                    "description": "Inscrição para o 4º Desafio 200k Porto Velho-Humaitá",
                    "category_id": "sports_tickets"
                }
            ],
            "payer": {
                "first_name": first_name,
                "last_name": last_name,
                "email": data.get('user_email')
            },
            "payment_methods": {
                "excluded_payment_methods": [
                    {"id": "bolbradesco"},
                    {"id": "pix"}
                ],
                "excluded_payment_types": [
                    {"id": "ticket"},
                    {"id": "bank_transfer"}
                ],
                "installments": 12
            },
            "back_urls": back_urls,
            "auto_return": "approved",
            "statement_descriptor": "ECM RUN",
            "external_reference": data.get('user_idatleta'),
            "notification_url": f"{back_urls['success'].rsplit('/', 1)[0]}/webhook"
        }
        
        # Log da preference antes de criar
        print("Preference data:", preference_data)
        
        preference_response = sdk.preference().create(preference_data)
        print("Resposta do MP:", preference_response)
        
        if "response" not in preference_response:
            raise Exception("Erro na resposta do Mercado Pago: " + str(preference_response))
            
        preference = preference_response["response"]
        
        return jsonify({
            "id": preference["id"],
            "init_point": preference["init_point"]
        })
    
    except Exception as e:
        print("Erro detalhado:", str(e))
        return jsonify({"error": str(e)}), 400

@app.route('/lanca-pagamento-cartao/<payment_id>')
def lanca_pagamento_cartao(payment_id):
    
    try:    
        # Verificar se já não foi processado antes
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM ecmrun.INSCRICAO WHERE IDPAGAMENTO = %s", (payment_id,))
        existing_record = cur.fetchone()
        
        if not existing_record:
            # Calculate valor_pgto (total payment)
            valor = float(session.get('valorAtual', 0))
            taxa = float(session.get('valorTaxa', 0))
            valoratual = valor + taxa
            valor_pgto = float(session.get('valorTotal', 0))
            desconto = valoratual - valor_pgto 
            formaPagto = 'CARTÃO DE CRÉDITO'
            camiseta = session.get('Camisa')
            equipe = session.get('Equipe')
            apoio = session.get('Apoio')
            equipe200 = session.get('Equipe200')
            integrantes = session.get('Integrantes')

            data_e_hora_atual = datetime.now()
            fuso_horario = timezone('America/Manaus')
            data_e_hora_manaus = data_e_hora_atual.astimezone(fuso_horario)
            data_pagamento = data_e_hora_manaus.strftime('%d/%m/%Y %H:%M')
                            
            # Get additional data from session
            idatleta = session.get('idAtleta')
            cpf = session.get('CPF')
            # idatleta = session.get('user_idatleta')
            # cpf = session.get('user_cpf')
            
            # Insert payment record
            query = """
            INSERT INTO ecmrun.INSCRICAO (
                IDATLETA, CPF, IDEVENTO, IDITEM, CAMISETA, APOIO, 
                NOME_EQUIPE, INTEGRANTES, VALOR, TAXA, DESCONTO,
                VALOR_PGTO, DTPAGAMENTO, FLSTATUS, FORMAPGTO, 
                IDPAGAMENTO, FLMAIL, EQUIPE
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """
            
            params = (
                idatleta,                            # IDATLETA
                cpf,                                 # CPF
                1,                                   # IDEVENTO (hardcoded as 1 for this event)
                session.get('cat_iditem'),           # IDITEM
                camiseta,                            # CAMISETA
                apoio,                               # APOIO
                equipe200,                           # NOME_EQUIPE
                integrantes,                         # INTEGRANTES
                valor,                               # VALOR
                taxa,                                # TAXA
                desconto,                            # DESCONTO
                valor_pgto,                          # VALOR_PGTO
                data_pagamento,                      # DTPAGAMENTO
                'CONFIRMADO',                        # FLSTATUS
                formaPagto,                          # FORMAPGTO
                payment_id,                          # IDPAGAMENTO
                'N',
                equipe
            )
            
            cur.execute(query, params)
            mysql.connection.commit()
            cur.close()
            
            print("Registro de pagamento inserido com sucesso!")
            
            return jsonify({
                'success': True,
                'status': 'approved',
                'message': 'Pagamento processado e registrado'
            })
        else:
            print("Pagamento já processado anteriormente")
            return jsonify({
                'success': True,
                'status': 'approved',
                'message': 'Pagamento já processado'
            })
    
        
    except Exception as e:
        print(f"Erro ao gerar lançamento: {str(e)}")
        # Ensure JSON is returned even on error
        return jsonify({
            'success': False, 
            'message': str(e),
            'status': 'error'
        }), 500

@app.route('/pesquisa-cupom/<int:categoria_id>/<cpf>/<cupom>')
def pesquisa_cupom(categoria_id, cpf, cupom):
    try:
        print(f"Recebido pedido de validação - Categoria: {categoria_id}, CPF: {cpf}, Cupom: {cupom}")
        
        cur = mysql.connection.cursor()
        query = "SELECT IDCUPOM, IDPAGAMENTO FROM ecmrun.CUPOM WHERE UTILIZADO = 'N' AND IDMODALIDADE = %s AND CPF = %s AND CUPOM = %s"
        
        print(f"Executando query: {query} com parâmetros: {(categoria_id, cpf, cupom)}")
        
        cur.execute(query, (categoria_id, cpf, cupom))
        result = cur.fetchone()
        
        print(f"Resultado da query: {result}")
        
        cur.close()

        if result:
            return jsonify({
                'success': True,
                'idcupom': result[0],
                'idpagamento': result[1]
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Número do cupom não encontrado ou não vinculado a este CPF e/ou Modalidade selecionada. Verifique e tente novamente.'
            })
    except Exception as e:
        print(f"Erro na validação do cupom: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/inscricao-copum/<id_cupom>', methods=['POST'])
def inscricao_copum(id_cupom):
    try:    
        cur = mysql.connection.cursor()
        query = "SELECT * FROM ecmrun.CUPOM WHERE IDCUPOM = %s"
        print(f"Executando query: {query} com parâmetros: {id_cupom}")
        
        cur.execute(query, id_cupom)
        result = cur.fetchone()
        print(f"Resultado da query: {result}")
        
        if result:
            # Extraindo dados do cupom
            cupom = result[1]
            cpf = result[2]
            idpagamento = result[3]
            formaPagto = result[4]
            data_pagamento = result[5]
            
            # Corrigindo a conversão dos valores decimais
            valor = float(result[6])
            taxa = float(result[7])
            valor_pgto = float(result[8])
            valoratual = valor + taxa
            iditem = result[9]
            desconto = valoratual - valor_pgto 
            
            # Obtendo dados da sessão
            camiseta = request.form.get('camiseta')
            equipe = request.form.get('equipe')
            apoio = request.form.get('apoio')
            equipe200 = request.form.get('equipe200')
            integrantes = request.form.get('integrantes')
        
            idatleta = session.get('user_idatleta')
            
            # Query de inserção
            query = """
            INSERT INTO ecmrun.INSCRICAO (
                IDATLETA, CPF, IDEVENTO, IDITEM, CAMISETA, APOIO, 
                NOME_EQUIPE, INTEGRANTES, VALOR, TAXA, DESCONTO,
                VALOR_PGTO, DTPAGAMENTO, FLSTATUS, FORMAPGTO, 
                IDPAGAMENTO, FLMAIL, EQUIPE, CUPOM
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """
            
            params = (
                idatleta,          # IDATLETA
                cpf,               # CPF
                1,                 # IDEVENTO (hardcoded as 1 for this event)
                iditem,            # IDITEM
                camiseta,          # CAMISETA
                apoio,             # APOIO
                equipe200,         # NOME_EQUIPE
                integrantes,       # INTEGRANTES
                valor,             # VALOR
                taxa,              # TAXA
                desconto,          # DESCONTO
                valor_pgto,        # VALOR_PGTO
                data_pagamento,    # DTPAGAMENTO
                'CONFIRMADO',      # FLSTATUS
                formaPagto,        # FORMAPGTO
                idpagamento,       # IDPAGAMENTO
                'N',              # FLMAIL
                equipe,           # EQUIPE
                cupom             # CUPOM
            )

            print(f"INSERT: {query}")
            print(f"Parametros: {params}")
                    
            cur.execute(query, params)
            mysql.connection.commit()
            
            print("Registro de pagamento inserido com sucesso!")
            
            # Atualizando status do cupom
            query = "UPDATE ecmrun.CUPOM SET UTILIZADO = 'S' WHERE IDCUPOM = %s"
            print(f"Executando Update: {query} com parâmetros: {id_cupom}")
            cur.execute(query, id_cupom)
            mysql.connection.commit()
            
            cur.close()
            
            return jsonify({
                'success': True,
                'message': 'Inscrição processada com sucesso'
            })
        else:
            print("Lancamento já processado anteriormente")
            return jsonify({
                'success': True,
                'message': 'Inscrição processada anteriormente'
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro ao processar inscrição: {str(e)}'
        }), 500
    
@app.route('/gerar_cupom', methods=['POST'])
def gerar_cupom():
    # Check if user is authenticated (has passed the admin password check)
    if not session.get('authenticated'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        # Get form data
        data = request.form
        modalidade = data.get('modalidade')
        cpf = data.get('cpf', '').replace('.', '').replace('-', '')  # Remove formatting
        bonifica = 'S' if data.get('bonifica') == 'on' else 'N'
        
        # Se for bonificação, definir valores padrão para campos de pagamento
        if bonifica == 'S':
            idpagamento = ''
            dtpagamento = ''
            formapgto = ''
            vlinscricao = '0'
            vltaxa = '0'
            vlpago = '0'
        else:
            idpagamento = data.get('idpagamento', '')
            dtpagamento = data.get('dtpagamento', '')
            formapgto = data.get('formapgto', '')
            vlinscricao = data.get('vlinscricao', '0').replace('.', '').replace(',', '.')
            vltaxa = data.get('vltaxa', '0').replace('.', '').replace(',', '.')
            vlpago = data.get('vlpago', '0').replace('.', '').replace(',', '.')
        
        # Garantir que valores numéricos sejam válidos
        try:
            vlinscricao_float = float(vlinscricao) if vlinscricao else 0.0
            vltaxa_float = float(vltaxa) if vltaxa else 0.0
            vlpago_float = float(vlpago) if vlpago else 0.0
        except ValueError as ve:
            print(f"Erro de conversão de valor: {ve}")
            return jsonify({'success': False, 'error': 'Valores monetários inválidos'}), 400
        
        # Generate random 5-character coupon code (uppercase letters and numbers)
        #cupom = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        numeros = random.choices(string.digits, k=2)
        # Gerar 3 letras maiúsculas aleatórias
        letras = random.choices(string.ascii_uppercase, k=3)
        # Juntar todos os caracteres
        todos_caracteres = numeros + letras
        # Embaralhar os caracteres
        random.shuffle(todos_caracteres)
        # Converter lista de caracteres para string
        cupom = ''.join(todos_caracteres)        



        # Connect to database
        cursor = mysql.connection.cursor()
        
        try:
            # Insert into database
            query = """
            INSERT INTO CUPOM (CUPOM, CPF, IDPAGAMENTO, FORMAPAGTO, DTPAGAMENTO, VALOR, TAXA, VALOR_PGTO, IDMODALIDADE, UTILIZADO, BONIFICA)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                cupom, 
                cpf, 
                idpagamento, 
                formapgto, 
                dtpagamento, 
                vlinscricao_float, 
                vltaxa_float, 
                vlpago_float, 
                int(modalidade), 
                'N',  # Not used initially
                bonifica
            ))
            
            # Commit to database
            mysql.connection.commit()

            # Verificar se existe um atleta cadastrado com esse CPF
            cursor.execute("SELECT EMAIL FROM ATLETA WHERE CPF = %s", (cpf,))
            resultado = cursor.fetchone()
            
            # Obter a descrição da modalidade
            cursor.execute("SELECT DESCRICAO FROM EVENTO_MODALIDADE WHERE IDITEM = %s", (modalidade,))
            modalidade_result = cursor.fetchone()
            desc_modalidade = modalidade_result[0] if modalidade_result else "Não especificada"

            # Se encontrou o atleta, enviar email
            if resultado and resultado[0]:
                email_atleta = resultado[0]
                
                # Enviar email
                try:
                    sender = "ECM RUN <ecmsistemasdeveloper@gmail.com>"
                    msg = Message(
                        'Cupom para o 4º Desafio 200k',
                        sender=sender,
                        recipients=[email_atleta]
                    )
                    
                    # Template HTML do email
                    if bonifica == 'N':
                        msg.html = f"""
                        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                            <h2 style="color: #4376ac;">Verificação de Cadastro - ECM Run</h2>
                            <p>Olá,</p>
                            <p>Foi gerado um cupom em seu CPF para o 4º Desafio 200k:</p>
                            <h1 style="color: #4376ac; font-size: 32px; letter-spacing: 5px;">{cupom}</h1>
                            <p>Para validar sua inscrição, você deve preencher os requisitos abaixo:</p>
                            <p>Cupom válido somente para seu CPF;</p>
                            <p>Categoria: <b>{desc_modalidade}<b>;</p>
                            <p>Forma de Pagamento: <b>{formapgto}</b></p>
                            <br>
                            <p>Atenciosamente,<br>Equipe ECM Run</p>
                        </div>
                        """
                    else:
                        msg.html = f"""
                        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                            <h2 style="color: #4376ac;">Verificação de Cadastro - ECM Run</h2>
                            <p>Olá,</p>
                            <p>Foi gerado um cupom em seu CPF para o 4º Desafio 200k:</p>
                            <h1 style="color: #4376ac; font-size: 32px; letter-spacing: 5px;">{cupom}</h1>
                            <p>Para validar sua inscrição, você deve preencher os requisitos abaixo:</p>
                            <p>Cupom válido somente para seu CPF;</p>
                            <p>Categoria: <b>{desc_modalidade}</b></p>
                            <br>
                            <p>Atenciosamente,<br>Equipe ECM Run</p>
                        </div>
                        """
                    
                    # Enviar email
                    mail.send(msg)
                    print(f"Email enviado com sucesso para {email_atleta}")
                except Exception as mail_error:
                    print(f"Erro ao enviar email: {mail_error}")
                    # Não retornamos erro aqui, pois o cupom já foi gerado com sucesso
                    # O email é apenas uma notificação adicional
            
            # Limpar a autenticação após uso bem-sucedido
            session.pop('authenticated', None)
            
            return jsonify({'success': True, 'cupom': cupom})
        
        except Exception as e:
            print(f"Database error: {e}")
            mysql.connection.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
        
        finally:
            cursor.close()
            
    except Exception as e:
        print(f"General error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/verificar_senha', methods=['POST'])
def verificar_senha():
    senha = request.form.get('senha')
    senha_adm = os.getenv('SENHA_ADM')
    
    if senha == senha_adm:
        # Criar uma autenticação temporária para esta requisição apenas
        session['authenticated'] = True
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Senha incorreta'})

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('desafio200k'))


# Rota para exibir a página de cadastro
@app.route('/apoio200k')
def apoio_cadastro():
    return render_template('apoio200k.html')

# API para buscar atletas
@app.route('/api/atletas')
def get_atletas():
    try:
        cursor = mysql.connection.cursor()
        query = """
            SELECT A.IDATLETA, CONCAT(A.NOME,' ',A.SOBRENOME) AS ATLETA
            FROM INSCRICAO I, ATLETA A
            WHERE A.IDATLETA = I.IDATLETA
            AND I.IDEVENTO = 1
            ORDER BY CONCAT(A.NOME,' ',A.SOBRENOME)
        """
        cursor.execute(query)
        atletas = cursor.fetchall()
        cursor.close()
        
        # Converter para lista de dicionários
        atletas_list = []
        for atleta in atletas:
            atletas_list.append({
                'IDATLETA': atleta[0],
                'ATLETA': atleta[1]
            })
        
        return jsonify(atletas_list)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API para cadastrar apoio
@app.route('/api/cadastrar-apoio', methods=['POST'])
def cadastrar_apoio():
    try:
        data = request.get_json()
        
        # Validar dados obrigatórios (veículo e placa agora são opcionais)
        if not all([data.get('nome'), data.get('celular'), 
                   data.get('idatleta'), data.get('aceite')]):
            return jsonify({'message': 'Nome, celular, atleta e aceite são obrigatórios'}), 400
        
        # Verificar se aceite é 'S'
        if data.get('aceite') != 'S':
            return jsonify({'message': 'É necessário aceitar o regulamento'}), 400
        
        cursor = mysql.connection.cursor()
        
        # Verificar se já existe apoio com mesmo nome e celular para o mesmo atleta
        check_query = """
            SELECT COUNT(*) FROM APOIO 
            WHERE UPPER(NOME) = %s AND CELULAR = %s AND IDATLETA = %s
        """
        cursor.execute(check_query, (
            data['nome'].upper().strip(),
            data['celular'].strip(),
            data['idatleta']
        ))
        
        if cursor.fetchone()[0] > 0:
            cursor.close()
            return jsonify({'message': 'Já existe um apoio cadastrado com este nome e celular para este atleta'}), 400
        
        # Obter data e hora de Manaus
        data_e_hora_atual = datetime.now()
        fuso_horario = timezone('America/Manaus')
        data_e_hora_manaus = data_e_hora_atual.astimezone(fuso_horario)
        
        # Inserir novo apoio
        insert_query = """
            INSERT INTO APOIO (NOME, CELULAR, VEICULO, PLACA, IDATLETA, DT_CADASTRO, ACEITE)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(insert_query, (
            data['nome'].upper().strip(),
            data['celular'].strip(),
            data.get('veiculo', '').upper().strip(),
            data.get('placa', '').upper().strip(),
            data['idatleta'],
            data_e_hora_manaus,
            data['aceite']
        ))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'message': 'Apoio cadastrado com sucesso'}), 200
    
    except Exception as e:
        return jsonify({'message': f'Erro interno do servidor: {str(e)}'}), 500

#######################

# Rota para renderizar a página principal
@app.route('/listainscricao200k')
def lista_inscricao():
    print("DEBUG: Renderizando página listainscricao200k.html")
    return render_template('listainscricao200k.html')

# Rota para verificar senha
@app.route('/verificar_senha1', methods=['POST'])
def verificar_senha1():
    print("DEBUG: Verificando senha...")
    try:
        data = request.get_json()
        print(f"DEBUG: Dados recebidos: {data}")
        
        senha_informada = data.get('senha')
        senha_correta = os.getenv('SENHA_ACESSO')
        
        print(f"DEBUG: Senha informada: {senha_informada}")
        print(f"DEBUG: Senha do ambiente existe: {senha_correta is not None}")
                
        if senha_informada == senha_correta:
            session['autenticado'] = True
            print("DEBUG: Autenticação bem-sucedida")
            return jsonify({'success': True})
        else:
            print("DEBUG: Senha incorreta")
            return jsonify({'success': False, 'message': 'Senha incorreta'})
            
    except Exception as e:
        print(f"DEBUG: Erro na verificação da senha: {str(e)}")
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

# Rota para buscar eventos
@app.route('/api/eventos1')
def get_eventos1():
    print("DEBUG: Buscando eventos...")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        print("DEBUG: Conexão com banco estabelecida")
        
        cursor.execute("SELECT IDEVENTO, DESCRICAO FROM EVENTO")
        eventos = cursor.fetchall()
        cursor.close()
        
        print(f"DEBUG: Encontrados {len(eventos)} eventos")
        
        eventos_list = []
        for evento in eventos:
            eventos_list.append({
                'IDEVENTO': evento[0],
                'DESCRICAO': evento[1]
            })
        
        print(f"DEBUG: Retornando eventos: {eventos_list}")
        return jsonify(eventos_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar eventos: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para buscar modalidades por evento
@app.route('/api/modalidades1/<int:evento_id>')
def get_modalidades1(evento_id):
    print(f"DEBUG: Buscando modalidades para evento {evento_id}")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT IDITEM, DESCRICAO FROM EVENTO_MODALIDADE WHERE IDEVENTO = %s", (evento_id,))
        modalidades = cursor.fetchall()
        cursor.close()
        
        print(f"DEBUG: Encontradas {len(modalidades)} modalidades")
        
        modalidades_list = []
        for modalidade in modalidades:
            modalidades_list.append({
                'IDITEM': modalidade[0],
                'DESCRICAO': modalidade[1]
            })
        
        return jsonify(modalidades_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar modalidades: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/modalidades2/<int:evento_id>')
def get_modalidades2(evento_id):
    print(f"DEBUG: Buscando modalidades para evento {evento_id}")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT IDITEM, DESCRICAO FROM EVENTO_MODALIDADE WHERE IDITEM <> 1 AND IDEVENTO = %s", (evento_id,))
        modalidades = cursor.fetchall()
        cursor.close()
        
        print(f"DEBUG: Encontradas {len(modalidades)} modalidades")
        
        modalidades_list = []
        for modalidade in modalidades:
            modalidades_list.append({
                'IDITEM': modalidade[0],
                'DESCRICAO': modalidade[1]
            })
        
        return jsonify(modalidades_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar modalidades: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para buscar inscrições por evento e modalidade
@app.route('/api/inscricoes/<int:evento_id>')
@app.route('/api/inscricoes/<int:evento_id>/<int:modalidade_id>')
def get_inscricoes(evento_id, modalidade_id=None):
    print(f"DEBUG: Buscando inscrições para evento {evento_id}, modalidade {modalidade_id}")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        
        if modalidade_id:
            query = """
            SELECT CONCAT(COALESCE(I.NUPEITO, ''),' ',A.NOME,' ',A.SOBRENOME) AS ATLETA, 
                   I.CAMISETA,
                   EV.DESCRICAO,
                   I.IDINSCRICAO,
                   A.SEXO,
                   I.FLSTATUS,
                   I.NUPEITO
            FROM ATLETA A, INSCRICAO I, EVENTO_MODALIDADE EV
            WHERE 
            EV.IDITEM = I.IDITEM
            AND A.IDATLETA = I.IDATLETA
            AND I.IDEVENTO = %s
            AND I.IDITEM = %s
            ORDER BY CONCAT(A.NOME,' ',A.SOBRENOME)
            """
            cursor.execute(query, (evento_id, modalidade_id))
        else:
            query = """
            SELECT CONCAT(COALESCE(I.NUPEITO, ''),' ',A.NOME,' ',A.SOBRENOME) AS ATLETA, 
                   I.CAMISETA,
                   EV.DESCRICAO,
                   I.IDINSCRICAO,
                   A.SEXO,
                   I.FLSTATUS,
                   I.NUPEITO
            FROM ATLETA A, INSCRICAO I, EVENTO_MODALIDADE EV
            WHERE 
            EV.IDITEM = I.IDITEM
            AND A.IDATLETA = I.IDATLETA
            AND I.IDEVENTO = %s
            ORDER BY CONCAT(A.NOME,' ',A.SOBRENOME)
            """
            cursor.execute(query, (evento_id,))
            
        inscricoes = cursor.fetchall()
        cursor.close()
        
        print(f"DEBUG: Encontradas {len(inscricoes)} inscrições")
        
        inscricoes_list = []
        for inscricao in inscricoes:
            inscricoes_list.append({
                'ATLETA': inscricao[0],
                'CAMISETA': inscricao[1],
                'DESCRICAO': inscricao[2],
                'IDINSCRICAO': inscricao[3],
                'SEXO': inscricao[4],
                'FLSTATUS': inscricao[5],
                'NUPEITO': inscricao[6]
            })
        
        return jsonify(inscricoes_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar inscrições: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para buscar detalhes da inscrição
@app.route('/api/inscricao/<int:inscricao_id>')
def get_inscricao_detalhes(inscricao_id):
    print(f"DEBUG: Buscando detalhes da inscrição {inscricao_id}")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT I.IDINSCRICAO, I.CPF, I.APOIO, I.NOME_EQUIPE, I.INTEGRANTES,
            I.CAMISETA, I.VALOR, I.TAXA, I.DESCONTO, I.VALOR_PGTO,
            I.FORMAPGTO, I.EQUIPE, I.CUPOM, 
            CONCAT(A.NOME,' ',A.SOBRENOME) AS NOME_COMPLETO,
            A.DTNASCIMENTO, A.NRCELULAR, A.SEXO, A.IDATLETA,
            EV.DESCRICAO AS MODALIDADE, I.FLSTATUS, I.NUPEITO
        FROM INSCRICAO I
        JOIN ATLETA A ON A.IDATLETA = I.IDATLETA
        JOIN EVENTO_MODALIDADE EV ON EV.IDITEM = I.IDITEM
        WHERE I.IDINSCRICAO = %s
        """
        cursor.execute(query, (inscricao_id,))
        inscricao = cursor.fetchone()
        cursor.close()
        
        if inscricao:
            resultado = {
                'IDINSCRICAO': inscricao[0],
                'CPF': inscricao[1],
                'APOIO': inscricao[2],
                'NOME_EQUIPE': inscricao[3],
                'INTEGRANTES': inscricao[4],
                'CAMISETA': inscricao[5],
                'VALOR': float(inscricao[6]) if inscricao[6] else 0,
                'TAXA': float(inscricao[7]) if inscricao[7] else 0,
                'DESCONTO': float(inscricao[8]) if inscricao[8] else 0,
                'VALOR_PGTO': float(inscricao[9]) if inscricao[9] else 0,
                'FORMAPGTO': inscricao[10],
                'EQUIPE': inscricao[11],
                'CUPOM': inscricao[12],
                'NOME_COMPLETO': inscricao[13],
                'DTNASCIMENTO': inscricao[14],
                'NRCELULAR': inscricao[15],
                'SEXO': inscricao[16],
                'IDATLETA': inscricao[17], 
                'MODALIDADE': inscricao[18],
                'FLSTATUS': inscricao[19],
                'NUPEITO': inscricao[20]
            }
            print(f"DEBUG: Detalhes encontrados: {resultado}")
            return jsonify(resultado)
        else:
            print("DEBUG: Inscrição não encontrada")
            return jsonify({'error': 'Inscrição não encontrada'}), 404
            
    except Exception as e:
        print(f"DEBUG: Erro ao buscar detalhes: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/atualizar-inscricao', methods=['POST'])
def atualizar_inscricao():
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        data = request.json
        inscricao_id = data['inscricaoId']
        fpagto = data['formapagto']
        valor = float(data['valor'])
        taxa = float(data['taxa'])
        desconto = float(data['desconto'])
        valor_pago = valor + taxa - desconto
        status = data['status']
        npeito = data['npeito']
        
        cursor = mysql.connection.cursor()
        query = """
        UPDATE INSCRICAO 
        SET FORMAPGTO = %s, VALOR = %s, TAXA = %s, DESCONTO = %s, VALOR_PGTO = %s, FLSTATUS = %s, NUPEITO = %s
        WHERE IDINSCRICAO = %s
        """
        cursor.execute(query, (fpagto, valor, taxa, desconto, valor_pago, status, npeito, inscricao_id))
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True, 'message': 'Inscrição atualizada com sucesso'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Rota para logout
@app.route('/logout_coordenador', methods=['POST'])
def logout_coordenador():
    print("DEBUG: Fazendo logout")
    session.pop('autenticado', None)
    return jsonify({'success': True})

#########

# ===== ROTAS PARA SISTEMA DE EQUIPES =====

# Rota para buscar equipes por evento
@app.route('/api/equipes/<int:evento_id>')
def get_equipes(evento_id):
    print(f"DEBUG: Buscando equipes para evento {evento_id}")
    
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT E.IDEA, E.NOME_EQUIPE, EM.DESCRICAO
        FROM EQUIPE E, EVENTO_MODALIDADE EM
        WHERE EM.IDITEM = E.IDITEM
        AND E.IDEVENTO = %s
        ORDER BY E.NOME_EQUIPE
        """
        cursor.execute(query, (evento_id,))
        equipes = cursor.fetchall()
        cursor.close()
        
        print(f"DEBUG: Encontradas {len(equipes)} equipes")
        
        equipes_list = []
        for equipe in equipes:
            equipes_list.append({
                'IDEA': equipe[0],
                'NOME_EQUIPE': equipe[1],
                'DESCRICAO': equipe[2]
            })
        
        return jsonify(equipes_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar equipes: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para buscar dados de uma modalidade específica
@app.route('/api/modalidade1/<int:modalidade_id>')
def get_modalidade1(modalidade_id):
    print(f"DEBUG: Buscando modalidade {modalidade_id}")
    
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT IDITEM, IDEVENTO, DESCRICAO, DISTANCIA, KM, 
               VLINSCRICAO, VLMEIA, VLTAXA, NU_ATLETAS
        FROM EVENTO_MODALIDADE 
        WHERE IDITEM = %s
        """
        cursor.execute(query, (modalidade_id,))
        modalidade = cursor.fetchone()
        cursor.close()
        
        if modalidade:
            modalidade_data = {
                'IDITEM': modalidade[0],
                'IDEVENTO': modalidade[1],
                'DESCRICAO': modalidade[2],
                'DISTANCIA': modalidade[3],
                'KM': modalidade[4],
                'VLINSCRICAO': float(modalidade[5]) if modalidade[5] else 0,
                'VLMEIA': float(modalidade[6]) if modalidade[6] else 0,
                'VLTAXA': float(modalidade[7]) if modalidade[7] else 0,
                'NU_ATLETAS': modalidade[8]
            }
            return jsonify(modalidade_data)
        else:
            return jsonify({'error': 'Modalidade não encontrada'}), 404
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar modalidade: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para buscar atletas disponíveis para equipe
@app.route('/api/atletas-disponiveis/<int:evento_id>/<int:modalidade_id>')
def get_atletas_disponiveis(evento_id, modalidade_id):
    print(f"DEBUG: Buscando atletas disponíveis para evento {evento_id}, modalidade {modalidade_id}")
    
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT A.IDATLETA, CONCAT(A.NOME,' ',A.SOBRENOME) AS ATLETA
        FROM INSCRICAO I, ATLETA A
        WHERE NOT EXISTS (
            SELECT 1 
            FROM EQUIPE_ATLETAS EA 
            WHERE EA.IDATLETA = A.IDATLETA 
            AND EA.IDEVENTO = %s
        )
        AND I.IDITEM = %s
        AND I.IDEVENTO = %s
        AND A.IDATLETA = I.IDATLETA
        ORDER BY CONCAT(A.NOME,' ',A.SOBRENOME)
        """
        cursor.execute(query, (evento_id, modalidade_id, evento_id))
        atletas = cursor.fetchall()
        cursor.close()
        
        print(f"DEBUG: Encontrados {len(atletas)} atletas disponíveis")
        
        atletas_list = []
        for atleta in atletas:
            atletas_list.append({
                'IDATLETA': atleta[0],
                'ATLETA': atleta[1]
            })
        
        return jsonify(atletas_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar atletas disponíveis: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para criar equipe
@app.route('/api/criar-equipe', methods=['POST'])
def criar_equipe():
    print("DEBUG: Criando nova equipe")
    
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        data = request.json
        evento_id = data['eventoId']
        modalidade_id = data['modalidadeId']
        nome_equipe = data['nomeEquipe']
        atletas = data['atletas']
        
        print(f"DEBUG: Dados recebidos - Evento: {evento_id}, Modalidade: {modalidade_id}, Nome: {nome_equipe}")
        
        cursor = mysql.connection.cursor()
        
        # Buscar dados da modalidade para cálculos de KM
        cursor.execute("SELECT KM FROM EVENTO_MODALIDADE WHERE IDITEM = %s", (modalidade_id,))
        modalidade_data = cursor.fetchone()
        km_modalidade = modalidade_data[0] if modalidade_data else 0
        
        # Inserir equipe
        cursor.execute("""
            INSERT INTO EQUIPE (IDEVENTO, IDITEM, NOME_EQUIPE) 
            VALUES (%s, %s, %s)
        """, (evento_id, modalidade_id, nome_equipe))
        
        equipe_id = cursor.lastrowid
        print(f"DEBUG: Equipe criada com ID: {equipe_id}")
        
        # Inserir atletas da equipe
        for ordem, atleta in enumerate(atletas, 1):
            km_ini = (ordem - 1) * km_modalidade
            km_fim = ordem * km_modalidade
            
            cursor.execute("""
                INSERT INTO EQUIPE_ATLETAS (IDEA, IDEVENTO, IDATLETA, ORDEM, KM_INI, KM_FIM) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (equipe_id, evento_id, atleta['IDATLETA'], ordem, km_ini, km_fim))
            
            print(f"DEBUG: Atleta {atleta['NOME']} inserido - Ordem: {ordem}, KM: {km_ini}-{km_fim}")
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True, 'message': 'Equipe criada com sucesso'})
        
    except Exception as e:
        print(f"DEBUG: Erro ao criar equipe: {str(e)}")
        mysql.connection.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# Rota para buscar atletas de uma equipe
@app.route('/api/equipe-atletas/<int:equipe_id>')
def get_equipe_atletas(equipe_id):
    print(f"DEBUG: Buscando atletas da equipe {equipe_id}")
    
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        
        # Buscar dados da equipe
        cursor.execute("""
            SELECT E.IDEA, E.NOME_EQUIPE, E.IDEVENTO, E.IDITEM, EM.DESCRICAO
            FROM EQUIPE E, EVENTO_MODALIDADE EM
            WHERE E.IDEA = %s AND EM.IDITEM = E.IDITEM
        """, (equipe_id,))
        equipe_data = cursor.fetchone()
        
        if not equipe_data:
            return jsonify({'error': 'Equipe não encontrada'}), 404
        
        # Buscar atletas da equipe
        cursor.execute("""
            SELECT EA.IDATLETA, CONCAT(A.NOME,' ',A.SOBRENOME) AS ATLETA, 
                   EA.ORDEM, EA.KM_INI, EA.KM_FIM
            FROM EQUIPE_ATLETAS EA
            INNER JOIN ATLETA A ON A.IDATLETA = EA.IDATLETA
            WHERE EA.IDEA = %s
            ORDER BY EA.ORDEM
        """, (equipe_id,))
        atletas_data = cursor.fetchall()
        
        cursor.close()
        
        # Estruturar dados da equipe
        equipe = {
            'IDEA': equipe_data[0],
            'NOME_EQUIPE': equipe_data[1],
            'IDEVENTO': equipe_data[2],
            'IDITEM': equipe_data[3],
            'DESCRICAO': equipe_data[4]
        }
        
        # Estruturar dados dos atletas
        atletas = []
        for atleta in atletas_data:
            atletas.append({
                'IDATLETA': atleta[0],
                'ATLETA': atleta[1],
                'ORDEM': atleta[2],
                'KM_INI': atleta[3],
                'KM_FIM': atleta[4]
            })
        
        return jsonify({
            'equipe': equipe,
            'atletas': atletas
        })
        
    except Exception as e:
        print(f"Erro ao buscar atletas da equipe: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

# Rota para salvar nova ordem dos atletas
@app.route('/api/salvar-ordem-equipe', methods=['POST'])
def salvar_ordem_equipe():
    print("DEBUG: Salvando nova ordem da equipe")
    
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        data = request.get_json()
        equipe_id = data.get('equipeId')
        atletas = data.get('atletas')
        
        if not all([equipe_id, atletas]):
            return jsonify({'error': 'Dados incompletos'}), 400
        
        cursor = mysql.connection.cursor()
        
        # Buscar dados da equipe para pegar o KM da modalidade
        cursor.execute("""
            SELECT E.IDITEM, EM.KM
            FROM EQUIPE E
            INNER JOIN EVENTO_MODALIDADE EM ON EM.IDITEM = E.IDITEM
            WHERE E.IDEA = %s
        """, (equipe_id,))
        equipe_data = cursor.fetchone()
        
        if not equipe_data:
            return jsonify({'error': 'Equipe não encontrada'}), 404
        
        km_por_atleta = equipe_data[1]
        
        # Atualizar ordem dos atletas
        for atleta in atletas:
            ordem = atleta['ordem']
            id_atleta = atleta['idatleta']
            km_ini = (ordem - 1) * km_por_atleta
            km_fim = ordem * km_por_atleta
            
            cursor.execute("""
                UPDATE EQUIPE_ATLETAS 
                SET ORDEM = %s, KM_INI = %s, KM_FIM = %s
                WHERE IDEA = %s AND IDATLETA = %s
            """, (ordem, km_ini, km_fim, equipe_id, id_atleta))
        
        mysql.connection.commit()
        cursor.close()
        
        return jsonify({'success': True, 'message': 'Ordem salva com sucesso'})
        
    except Exception as e:
        print(f"Erro ao salvar ordem: {str(e)}")
        mysql.connection.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/api/apoios/<int:atleta_id>')
def get_apoios_atleta(atleta_id):
    print(f"DEBUG: Buscando apoios do atleta {atleta_id}")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        query = """
        SELECT IDAPOIO, NOME, CELULAR, VEICULO, PLACA
        FROM APOIO 
        WHERE IDATLETA = %s
        ORDER BY NOME
        """
        cursor.execute(query, (atleta_id,))
        apoios = cursor.fetchall()
        cursor.close()
        
        resultado = []
        for apoio in apoios:
            veiculo_placa = ""
            if apoio[3] or apoio[4]:  # Se tem veículo ou placa
                veiculo = apoio[3] or ""
                placa = apoio[4] or ""
                veiculo_placa = f"{veiculo} {placa}".strip()
            
            resultado.append({
                'IDAPOIO': apoio[0],
                'NOME': apoio[1],
                'CELULAR': apoio[2],
                'VEICULO_PLACA': veiculo_placa
            })
        
        print(f"DEBUG: {len(resultado)} apoios encontrados")
        return jsonify(resultado)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar apoios: {str(e)}")
        return jsonify({'error': str(e)}), 500

###########
@app.route('/apoio_organizacao200k')
def apoio_organizacao200k():
    """Rota para servir a página HTML de cadastro de apoio"""
    return render_template('apoio_organizacao200k.html')

@app.route('/obter_pontos_apoio_org200k', methods=['GET'])
def obter_pontos_apoio_org200k():
    """Rota para obter todos os pontos de apoio disponíveis"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT IDPONTO, DE_PONTO 
            FROM PONTO_APOIO_ORG_200k 
            ORDER BY IDPONTO
        """)
        rows = cur.fetchall()
        cur.close()
        
        pontos = []
        for row in rows:
            pontos.append({
                'IDPONTO': row[0],
                'DE_PONTO': row[1]
            })
        
        return jsonify(pontos)
    
    except Exception as e:
        return jsonify({'error': f'Erro ao obter pontos de apoio: {str(e)}'}), 500

@app.route('/obter_proximo_id_apoio_org200k', methods=['GET'])
def obter_proximo_id_apoio_org200k():
    """Rota para obter o próximo ID disponível para APOIO_ORG_200k"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT COALESCE(MAX(IDAPOIO_ORG), 0) + 1 as proximo_id 
            FROM APOIO_ORG_200k
        """)
        row = cur.fetchone()
        cur.close()
        
        proximo_id = row[0] if row else 1
        
        return jsonify({'proximo_id': proximo_id})
    
    except Exception as e:
        return jsonify({'error': f'Erro ao obter próximo ID: {str(e)}'}), 500

@app.route('/salvar_apoio_org200k', methods=['POST'])
def salvar_apoio_org200k():
    """Rota para salvar o apoio da organização e seus itens"""
    try:
        print("=== INICIO salvar_apoio_org200k ===")
        
        dados = request.get_json()
        print(f"Dados recebidos: {dados}")
        
        # Validar dados recebidos
        if not dados:
            print("Erro: Dados não informados")
            return jsonify({'message': 'Dados não informados'}), 400
        
        id_apoio_org = dados.get('idApoioOrg')
        nome = dados.get('nome', '').strip()
        celular = dados.get('celular', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        itens = dados.get('itens', [])
        
        print(f"ID: {id_apoio_org}, Nome: {nome}, Celular: {celular}")
        print(f"Itens: {itens}")
        
        # Validações
        if not nome:
            print("Erro: Nome é obrigatório")
            return jsonify({'message': 'Nome é obrigatório'}), 400
        
        if not celular or len(celular) != 11:
            print(f"Erro: Celular inválido - {celular} - tamanho: {len(celular)}")
            return jsonify({'message': 'Celular deve ter 11 dígitos'}), 400
        
        if not itens:
            print("Erro: Nenhum item de apoio")
            return jsonify({'message': 'Pelo menos um item de apoio é obrigatório'}), 400
        
        if not id_apoio_org:
            print("Erro: ID do apoio não informado")
            return jsonify({'message': 'ID do apoio não informado'}), 400
        
        # Validar datas dos itens
        print("Validando datas dos itens...")
        data_minima = datetime(2025, 7, 4, 12, 0)
        data_maxima = datetime(2025, 7, 6, 19, 0)
        
        for i, item in enumerate(itens):
            print(f"Validando item {i}: {item}")
            try:
                dt_inicio = datetime.fromisoformat(item['DTHR_INICIO'].replace('T', ' '))
                dt_final = datetime.fromisoformat(item['DTHR_FINAL'].replace('T', ' '))
                
                print(f"Item {i} - Início: {dt_inicio}, Final: {dt_final}")
                
                if dt_inicio < data_minima or dt_inicio > data_maxima:
                    print(f"Erro: Data início fora do intervalo - {dt_inicio}")
                    return jsonify({'message': 'Data/hora de início deve estar entre 04/07/2025 12:00 e 06/07/2025 19:00'}), 400
                
                if dt_final < data_minima or dt_final > data_maxima:
                    print(f"Erro: Data final fora do intervalo - {dt_final}")
                    return jsonify({'message': 'Data/hora final deve estar entre 04/07/2025 12:00 e 06/07/2025 19:00'}), 400
                
                if dt_final <= dt_inicio:
                    print(f"Erro: Data final <= início")
                    return jsonify({'message': 'Data/hora final deve ser posterior à data/hora inicial'}), 400
                    
            except ValueError as ve:
                print(f"Erro no formato da data: {ve}")
                return jsonify({'message': 'Formato de data/hora inválido'}), 400
            except Exception as e:
                print(f"Erro inesperado na validação de data: {e}")
                return jsonify({'message': f'Erro na validação de data: {str(e)}'}), 400
        
        # Iniciar transação
        print("Iniciando transação com banco de dados...")
        cur = None
        
        try:
            cur = mysql.connection.cursor()
            print("Cursor criado com sucesso")
            
            # Verificar se o ID já existe
            print(f"Verificando se ID {id_apoio_org} já existe...")
            cur.execute("SELECT COUNT(*) FROM APOIO_ORG_200k WHERE IDAPOIO_ORG = %s", (id_apoio_org,))
            count = cur.fetchone()[0]
            print(f"Registros encontrados com este ID: {count}")
            
            if count > 0:
                print("Erro: ID já existe")
                return jsonify({'message': 'ID já existe, recarregue a página'}), 400
            
            # Inserir registro principal na APOIO_ORG_200k
            print("Inserindo registro principal...")
            sql_principal = """
                INSERT INTO APOIO_ORG_200k (IDAPOIO_ORG, NOME, CELULAR, DT_CADASTRO) 
                VALUES (%s, %s, %s, NOW())
            """
            parametros_principal = (id_apoio_org, nome, celular)
            print(f"SQL: {sql_principal}")
            print(f"Parâmetros: {parametros_principal}")
            
            cur.execute(sql_principal, parametros_principal)
            print("Registro principal inserido com sucesso")
            
            # Inserir itens na APOIO_ORG_ITENS_200k
            print("Inserindo itens...")
            for i, item in enumerate(itens):
                dt_inicio_str = item['DTHR_INICIO'].replace('T', ' ')
                dt_final_str = item['DTHR_FINAL'].replace('T', ' ')
                
                # Correção: usar IDPUNTO ao invés de IDPONTO (conforme enviado do frontend)
                id_ponto = item.get('IDPUNTO') or item.get('IDPONTO')
                print(f"Item {i} - ID Ponto: {id_ponto}, Início: {dt_inicio_str}, Final: {dt_final_str}")
                
                sql_item = """
                    INSERT INTO APOIO_ORG_ITENS_200k (IDAPOIO_ORG, IDPONTO, DTHR_INICIO, DTHR_FINAL) 
                    VALUES (%s, %s, %s, %s)
                """
                parametros_item = (id_apoio_org, id_ponto, dt_inicio_str, dt_final_str)
                print(f"SQL Item: {sql_item}")
                print(f"Parâmetros Item: {parametros_item}")
                
                cur.execute(sql_item, parametros_item)
                print(f"Item {i} inserido com sucesso")
            
            # Confirmar transação
            print("Confirmando transação...")
            mysql.connection.commit()
            print("Transação confirmada com sucesso")
            
            return jsonify({
                'success': True, 
                'message': 'Apoio registrado com sucesso!',
                'id_apoio': id_apoio_org
            })
        
        except Exception as e:
            # Desfazer transação em caso de erro
            print(f"ERRO na transação do banco: {str(e)}")
            print(f"Tipo do erro: {type(e)}")
            import traceback
            traceback.print_exc()
            
            if mysql.connection:
                mysql.connection.rollback()
                print("Rollback executado")
            
            return jsonify({'message': f'Erro ao salvar no banco de dados: {str(e)}'}), 500
        
        finally:
            # Garantir que o cursor seja fechado
            if cur:
                cur.close()
                print("Cursor fechado")
    
    except Exception as e:
        print(f"ERRO GERAL na rota: {str(e)}")
        print(f"Tipo do erro: {type(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'message': f'Erro interno do servidor: {str(e)}'}), 500


@app.route('/consultar_apoio_org200k/<int:id_apoio>', methods=['GET'])
def consultar_apoio_org200k(id_apoio):
    """Rota para consultar um apoio específico (para futura página de edição)"""
    try:
        cur = mysql.connection.cursor()
        
        # Buscar dados principais
        cur.execute("""
            SELECT IDAPOIO_ORG, NOME, CELULAR, DT_CADASTRO 
            FROM APOIO_ORG_200k 
            WHERE IDAPOIO_ORG = %s
        """, (id_apoio,))
        
        apoio_row = cur.fetchone()
        if not apoio_row:
            cur.close()
            return jsonify({'error': 'Apoio não encontrado'}), 404
        
        # Buscar itens
        cur.execute("""
            SELECT ai.ID, ai.IDPONTO, p.DE_PONTO, ai.DTHR_INICIO, ai.DTHR_FINAL
            FROM APOIO_ORG_ITENS_200k ai
            INNER JOIN PONTO_APOIO_ORG_200k p ON ai.IDPONTO = p.IDPONTO
            WHERE ai.IDAPOIO_ORG = %s
            ORDER BY ai.DTHR_INICIO
        """, (id_apoio,))
        
        itens_rows = cur.fetchall()
        cur.close()
        
        # Montar resposta
        apoio = {
            'IDAPOIO_ORG': apoio_row[0],
            'NOME': apoio_row[1],
            'CELULAR': apoio_row[2],
            'DT_CADASTRO': apoio_row[3].isoformat() if apoio_row[3] else None,
            'itens': []
        }
        
        for item_row in itens_rows:
            apoio['itens'].append({
                'ID': item_row[0],
                'IDPONTO': item_row[1],
                'DE_PONTO': item_row[2],
                'DTHR_INICIO': item_row[3].isoformat() if item_row[3] else None,
                'DTHR_FINAL': item_row[4].isoformat() if item_row[4] else None
            })
        
        return jsonify(apoio)
    
    except Exception as e:
        return jsonify({'error': f'Erro ao consultar apoio: {str(e)}'}), 500

@app.route('/listar_apoios_org200k', methods=['GET'])
def listar_apoios_org200k():
    """Rota para listar todos os apoios (para futura página de administração)"""
    try:
        cur = mysql.connection.cursor()
        
        cur.execute("""
            SELECT a.IDAPOIO_ORG, a.NOME, a.CELULAR, a.DT_CADASTRO,
                   COUNT(ai.ID) as total_itens
            FROM APOIO_ORG_200k a
            LEFT JOIN APOIO_ORG_ITENS_200k ai ON a.IDAPOIO_ORG = ai.IDAPOIO_ORG
            GROUP BY a.IDAPOIO_ORG, a.NOME, a.CELULAR, a.DT_CADASTRO
            ORDER BY a.DT_CADASTRO DESC
        """)
        
        rows = cur.fetchall()
        cur.close()
        
        apoios = []
        for row in rows:
            apoios.append({
                'IDAPOIO_ORG': row[0],
                'NOME': row[1],
                'CELULAR': row[2],
                'DT_CADASTRO': row[3].isoformat() if row[3] else None,
                'TOTAL_ITENS': row[4]
            })
        
        return jsonify(apoios)
    
    except Exception as e:
        return jsonify({'error': f'Erro ao listar apoios: {str(e)}'}), 500

# Função auxiliar para popular tabela de pontos de apoio (execute uma vez)
@app.route('/popular_pontos_apoio_org200k', methods=['POST'])
def popular_pontos_apoio_org200k():
    """Rota para popular a tabela de pontos de apoio (usar apenas uma vez para configurar)"""
    try:
        pontos_exemplo = [
            'Largada',
            'KM 5',
            'KM 10',
            'KM 20',
            'KM 30',
            'KM 50',
            'KM 70',
            'KM 100',
            'KM 130',
            'KM 150',
            'KM 170',
            'KM 190',
            'Chegada',
            'Posto Médico',
            'Hidratação',
            'Apoio Técnico'
        ]
        
        cur = mysql.connection.cursor()
        
        for ponto in pontos_exemplo:
            cur.execute("""
                INSERT INTO PONTO_APOIO_ORG_200k (DE_PONTO) 
                VALUES (%s)
            """, (ponto,))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({'success': True, 'message': 'Pontos de apoio populados com sucesso!'})
    
    except Exception as e:
        return jsonify({'error': f'Erro ao popular pontos de apoio: {str(e)}'}), 500

# Rota para excluir um apoio (para futura página de administração)
@app.route('/excluir_apoio_org200k/<int:id_apoio>', methods=['DELETE'])
def excluir_apoio_org200k(id_apoio):
    """Rota para excluir um apoio e seus itens"""
    try:
        cur = mysql.connection.cursor()
        
        try:
            # Excluir itens primeiro (chave estrangeira)
            cur.execute("DELETE FROM APOIO_ORG_ITENS_200k WHERE IDAPOIO_ORG = %s", (id_apoio,))
            
            # Excluir apoio principal
            cur.execute("DELETE FROM APOIO_ORG_200k WHERE IDAPOIO_ORG = %s", (id_apoio,))
            
            if cur.rowcount == 0:
                mysql.connection.rollback()
                cur.close()
                return jsonify({'error': 'Apoio não encontrado'}), 404
            
            mysql.connection.commit()
            cur.close()
            
            return jsonify({'success': True, 'message': 'Apoio excluído com sucesso!'})
        
        except Exception as e:
            mysql.connection.rollback()
            cur.close()
            return jsonify({'error': f'Erro ao excluir apoio: {str(e)}'}), 500
    
    except Exception as e:
        return jsonify({'error': f'Erro interno: {str(e)}'}), 500


###########

# Rotas Flask para administração do apoio organizacional

@app.route('/api/apoio-admin002', methods=['GET'])
def listar_apoio_admin002():
    """Lista todos os registros de apoio com seus itens"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT 
                a.IDAPOIO_ORG,
                a.NOME,
                a.CELULAR,
                ai.ID as ITEM_ID,
                ai.IDPONTO,
                p.DE_PONTO,
                ai.DTHR_INICIO,
                ai.DTHR_FINAL
            FROM APOIO_ORG_200k a
            LEFT JOIN APOIO_ORG_ITENS_200k ai ON a.IDAPOIO_ORG = ai.IDAPOIO_ORG
            LEFT JOIN PONTO_APOIO_ORG_200k p ON ai.IDPONTO = p.IDPONTO
            ORDER BY a.IDAPOIO_ORG, ai.ID
        """)
        
        registros = cur.fetchall()
        cur.close()
        
        # Organizar dados por apoiador
        apoiadores = {}
        for registro in registros:
            id_apoio = registro[0]
            if id_apoio not in apoiadores:
                apoiadores[id_apoio] = {
                    'IDAPOIO_ORG': registro[0],
                    'NOME': registro[1],
                    'CELULAR': registro[2],
                    'itens': []
                }
            
            if registro[3]:  # Se tem item
                apoiadores[id_apoio]['itens'].append({
                    'ID': registro[3],
                    'IDPONTO': registro[4],
                    'DE_PONTO': registro[5],
                    'DTHR_INICIO': registro[6].strftime('%Y-%m-%dT%H:%M') if registro[6] else '',
                    'DTHR_FINAL': registro[7].strftime('%Y-%m-%dT%H:%M') if registro[7] else ''
                })
        
        return jsonify(list(apoiadores.values()))
    
    except Exception as e:
        return jsonify({'error': f'Erro ao listar apoio: {str(e)}'}), 500

# @app.route('/api/apoio-admin002', methods=['GET'])
# def listar_apoio_admin002():
#     """Lista todos os registros de apoio com seus itens"""
#     try:
#         cur = mysql.connection.cursor()
#         cur.execute("""
#             SELECT 
#                 a.IDAPOIO_ORG,
#                 a.NOME,
#                 a.CELULAR,
#                 ai.ID as ITEM_ID,
#                 ai.IDPONTO,
#                 p.DE_PONTO,
#                 ai.DTHR_INICIO,
#                 ai.DTHR_FINAL
#             FROM APOIO_ORG_200k a
#             LEFT JOIN APOIO_ORG_ITENS_200k ai ON a.IDAPOIO_ORG = ai.IDAPOIO_ORG
#             LEFT JOIN PONTO_APOIO_ORG_200k p ON ai.IDPONTO = p.IDPONTO
#             ORDER BY a.IDAPOIO_ORG, ai.ID
#         """)
        
#         registros = cur.fetchall()
#         cur.close()
        
#         # Organizar dados por apoiador
#         apoiadores = {}
#         for registro in registros:
#             id_apoio = registro[0]
#             if id_apoio not in apoiadores:
#                 apoiadores[id_apoio] = {
#                     'IDAPOIO_ORG': registro[0],
#                     'NOME': registro[1],
#                     'CELULAR': registro[2],
#                     'itens': []
#                 }
            
#             if registro[3]:  # Se tem item
#                 apoiadores[id_apoio]['itens'].append({
#                     'ID': registro[3],
#                     'IDPONTO': registro[4],
#                     'DE_PONTO': registro[5],
#                     'DTHR_INICIO': registro[6].strftime('%Y-%m-%dT%H:%M') if registro[6] else '',
#                     'DTHR_FINAL': registro[7].strftime('%Y-%m-%dT%H:%M') if registro[7] else ''
#                 })
        
#         return jsonify(list(apoiadores.values()))
    
#     except Exception as e:
#         return jsonify({'error': f'Erro ao listar apoio: {str(e)}'}), 500

@app.route('/api/pontos-apoio002', methods=['GET'])
def listar_pontos_apoio002():
    """Lista todos os pontos de apoio disponíveis"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT IDPONTO, DE_PONTO FROM PONTO_APOIO_ORG_200k ORDER BY IDPONTO")
        pontos = cur.fetchall()
        cur.close()
        
        pontos_list = []
        for ponto in pontos:
            pontos_list.append({
                'IDPONTO': ponto[0],
                'DE_PONTO': ponto[1]
            })
        
        return jsonify(pontos_list)
    
    except Exception as e:
        return jsonify({'error': f'Erro ao listar pontos: {str(e)}'}), 500

@app.route('/api/apoio-item002/<int:item_id>', methods=['PUT'])
def atualizar_item_apoio002(item_id):
    """Atualiza um item de apoio (datas/horários e ponto)"""
    try:
        data = request.json
        cur = mysql.connection.cursor()
        
        cur.execute("""
            UPDATE APOIO_ORG_ITENS_200k 
            SET IDPONTO = %s, DTHR_INICIO = %s, DTHR_FINAL = %s
            WHERE ID = %s
        """, (
            data.get('IDPONTO'),
            data.get('DTHR_INICIO') if data.get('DTHR_INICIO') else None,
            data.get('DTHR_FINAL') if data.get('DTHR_FINAL') else None,
            item_id
        ))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({'success': 'Item atualizado com sucesso'})
    
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': f'Erro ao atualizar item: {str(e)}'}), 500

@app.route('/api/apoio-org002/<int:apoio_id>', methods=['DELETE'])
def excluir_apoio002(apoio_id):
    """Exclui um apoiador e todos os seus itens"""
    try:
        cur = mysql.connection.cursor()
        
        # Primeiro exclui os itens
        cur.execute("DELETE FROM APOIO_ORG_ITENS_200k WHERE IDAPOIO_ORG = %s", (apoio_id,))
        
        # Depois exclui o apoiador
        cur.execute("DELETE FROM APOIO_ORG_200k WHERE IDAPOIO_ORG = %s", (apoio_id,))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({'success': 'Apoiador excluído com sucesso'})
    
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': f'Erro ao excluir apoiador: {str(e)}'}), 500

@app.route('/api/apoio-item002/<int:item_id>', methods=['DELETE'])
def excluir_item_apoio002(item_id):
    """Exclui apenas um item específico de apoio"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM APOIO_ORG_ITENS_200k WHERE ID = %s", (item_id,))
        mysql.connection.commit()
        cur.close()
        
        return jsonify({'success': 'Item excluído com sucesso'})
    
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': f'Erro ao excluir item: {str(e)}'}), 500

@app.route('/admin-apoio')
def admin_apoio002():
    """Página de administração do apoio"""
    return render_template('admin_apoio002.html')

#############################
@app.route('/cronometro200k')
def cronometro200k():
    """Página do cronômetro da ultramaratona"""
    return render_template('cronometro200k.html')

@app.route('/api/evento-data', methods=['GET'])
def obter_data_evento():
    """Rota para obter a data/hora do evento"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT DATAHORAEVENTO 
            FROM EVENTO 
            WHERE IDEVENTO = 1
        """)
        row = cur.fetchone()
        cur.close()
        
        if row:
            # Converter para timestamp (assumindo que o banco está em horário local)
            data_evento = row[0]
            
            # Se necessário, ajustar timezone (exemplo para Rondônia - UTC-4)
            if data_evento.tzinfo is None:
                # Assumir que é horário local de Rondônia
                tz_rondonia = pytz.timezone('America/Porto_Velho')
                data_evento = tz_rondonia.localize(data_evento)
            
            # Converter para timestamp em milissegundos
            timestamp = int(data_evento.timestamp() * 1000)
            
            return jsonify({
                'success': True,
                'dataHoraEvento': data_evento.isoformat(),
                'timestamp': timestamp
            })
        else:
            return jsonify({'success': False, 'error': 'Evento não encontrado'}), 404
    
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro ao obter data do evento: {str(e)}'}), 500

@app.route('/api/iniciar-cronometro', methods=['POST'])
def iniciar_cronometro():
    """Rota para marcar o início da corrida (opcional - para controle manual)"""
    try:
        # Atualizar a data/hora do evento para agora
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE EVENTO 
            SET DATAHORAEVENTO = NOW() 
            WHERE IDEVENTO = 1
        """)
        mysql.connection.commit()
        cur.close()
        
        return jsonify({'success': True, 'message': 'Cronômetro iniciado!'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro ao iniciar cronômetro: {str(e)}'}), 500


########

# Rota para exibir a página do dashboard
@app.route('/dashboard200k')
def dashboard200k():
    return render_template('dashboard200k.html')

# Rota para buscar dados das equipes
@app.route('/dashboard_api/equipes')
def dashboard_get_equipes():
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        
        query = """
        SELECT CONCAT(e.NOME_EQUIPE,' (',em.DEREDUZ,')') as EQUIPE,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 25 AND IDEA = e.IDEA) AS KM25,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 50 AND IDEA = e.IDEA) AS KM50,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 75 AND IDEA = e.IDEA) AS KM75,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 100 AND IDEA = e.IDEA) AS KM100,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 125 AND IDEA = e.IDEA) AS KM125,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 150 AND IDEA = e.IDEA) AS KM150,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 175 AND IDEA = e.IDEA) AS KM175,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 200 AND IDEA = e.IDEA) AS KM200,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K
           WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDEA = e.IDEA) 
             AND IDEA = e.IDEA) AS ULTIMAPARCIAL,
          CONCAT(
            TIMESTAMPDIFF(HOUR, 
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 0 AND IDEA = e.IDEA),
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K 
               WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDEA = e.IDEA) 
                 AND IDEA = e.IDEA)
            ),':',
            LPAD(TIMESTAMPDIFF(MINUTE, 
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 0 AND IDEA = e.IDEA),
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K 
               WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDEA = e.IDEA) 
                 AND IDEA = e.IDEA)
            ) % 60, 2, '0'),':',
            LPAD(TIMESTAMPDIFF(SECOND, 
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 0 AND IDEA = e.IDEA),
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K 
               WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDEA = e.IDEA) 
                 AND IDEA = e.IDEA)
            ) % 60, 2, '0')
          ) AS TEMPO   
        FROM EQUIPE e, EVENTO_MODALIDADE em
        WHERE em.IDITEM = e.IDITEM
        ORDER BY em.IDITEM
        """
        
        cursor.execute(query)
        equipes = cursor.fetchall()
        cursor.close()
        
        equipes_list = []
        for equipe in equipes:
            equipes_list.append({
                'EQUIPE': equipe[0],
                'KM25': equipe[1].strftime('%d/%m/%y %H:%M') if equipe[1] else '',
                'KM50': equipe[2].strftime('%d/%m/%y %H:%M') if equipe[2] else '',
                'KM75': equipe[3].strftime('%d/%m/%y %H:%M') if equipe[3] else '',
                'KM100': equipe[4].strftime('%d/%m/%y %H:%M') if equipe[4] else '',
                'KM125': equipe[5].strftime('%d/%m/%y %H:%M') if equipe[5] else '',
                'KM150': equipe[6].strftime('%d/%m/%y %H:%M') if equipe[6] else '',
                'KM175': equipe[7].strftime('%d/%m/%y %H:%M') if equipe[7] else '',
                'KM200': equipe[8].strftime('%d/%m/%y %H:%M') if equipe[8] else '',
                'ULTIMAPARCIAL': equipe[9].strftime('%d/%m/%y %H:%M') if equipe[9] else '',
                'TEMPO': equipe[10] if equipe[10] else ''
            })
        
        return jsonify(equipes_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar equipes: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Rota para buscar dados dos atletas solo
@app.route('/dashboard_api/atletas')
def dashboard_get_atletas():
    if not session.get('autenticado'):
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        
        query = """
        SELECT CONCAT(i.NUPEITO,' - ',a.NOME,' ',a.SOBRENOME) as NOME,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 25 AND IDATLETA = a.IDATLETA) AS KM25,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 50 AND IDATLETA = a.IDATLETA) AS KM50,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 75 AND IDATLETA = a.IDATLETA) AS KM75,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 100 AND IDATLETA = a.IDATLETA) AS KM100,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 125 AND IDATLETA = a.IDATLETA) AS KM125,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 150 AND IDATLETA = a.IDATLETA) AS KM150,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 175 AND IDATLETA = a.IDATLETA) AS KM175,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 200 AND IDATLETA = a.IDATLETA) AS KM200,
          (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K
           WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDATLETA = a.IDATLETA) 
             AND IDATLETA = a.IDATLETA) AS ULTIMAPARCIAL,
          CONCAT(
            TIMESTAMPDIFF(HOUR, 
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 0 AND IDATLETA = a.IDATLETA),
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K 
               WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDATLETA = a.IDATLETA) 
                 AND IDATLETA = a.IDATLETA)
            ),':',
            LPAD(TIMESTAMPDIFF(MINUTE, 
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 0 AND IDATLETA = a.IDATLETA),
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K 
               WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDATLETA = a.IDATLETA) 
                 AND IDATLETA = a.IDATLETA)
            ) % 60, 2, '0'),':',
            LPAD(TIMESTAMPDIFF(SECOND, 
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K WHERE KM = 0 AND IDATLETA = a.IDATLETA),
              (SELECT DATA_HORA FROM PROVA_PARCIAIS_200K 
               WHERE KM = (SELECT MAX(KM) FROM PROVA_PARCIAIS_200K WHERE IDATLETA = a.IDATLETA) 
                 AND IDATLETA = a.IDATLETA)
            ) % 60, 2, '0')
          ) AS TEMPO   
        FROM ATLETA a, INSCRICAO i, EVENTO_MODALIDADE em
        WHERE em.IDITEM = i.IDITEM
        AND i.IDITEM = 1
        AND i.IDATLETA = a.IDATLETA
        ORDER BY a.NOME, a.SOBRENOME
        """
        
        cursor.execute(query)
        atletas = cursor.fetchall()
        cursor.close()
        
        atletas_list = []
        for atleta in atletas:
            atletas_list.append({
                'NOME': atleta[0],
                'KM25': atleta[1].strftime('%d/%m/%y %H:%M') if atleta[1] else '',
                'KM50': atleta[2].strftime('%d/%m/%y %H:%M') if atleta[2] else '',
                'KM75': atleta[3].strftime('%d/%m/%y %H:%M') if atleta[3] else '',
                'KM100': atleta[4].strftime('%d/%m/%y %H:%M') if atleta[4] else '',
                'KM125': atleta[5].strftime('%d/%m/%y %H:%M') if atleta[5] else '',
                'KM150': atleta[6].strftime('%d/%m/%y %H:%M') if atleta[6] else '',
                'KM175': atleta[7].strftime('%d/%m/%y %H:%M') if atleta[7] else '',
                'KM200': atleta[8].strftime('%d/%m/%y %H:%M') if atleta[8] else '',
                'ULTIMAPARCIAL': atleta[9].strftime('%d/%m/%y %H:%M') if atleta[9] else '',
                'TEMPO': atleta[10] if atleta[10] else ''
            })
        
        return jsonify(atletas_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar atletas: {str(e)}")
        return jsonify({'error': str(e)}), 500

#################

@app.route('/lancamento200k')
def lancamento200k():
    """Renderiza a página de lançamento"""
    return render_template('lancamento200k.html')

@app.route('/api/lanca200k_parciais')
def lanca200k_parciais():
    """Busca as parciais disponíveis"""
    print("DEBUG: Buscando parciais...")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        cursor = mysql.connection.cursor()
        print("DEBUG: Conexão com banco estabelecida")
        
        cursor.execute("""
            SELECT KM, DEPARCIAL, IDPARCIAL FROM PARCIAIS_200K
            WHERE KM <> 0
            ORDER BY KM
        """)
        parciais = cursor.fetchall()
        cursor.close()
        
        print(f"DEBUG: Encontradas {len(parciais)} parciais")
        
        parciais_list = []
        for parcial in parciais:
            parciais_list.append({
                'KM': parcial[0],
                'DEPARCIAL': parcial[1],
                'IDPARCIAL': parcial[2]
            })
        
        print(f"DEBUG: Retornando parciais: {parciais_list}")
        return jsonify(parciais_list)
        
    except Exception as e:
        print(f"DEBUG: Erro ao buscar parciais: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/lanca200k_pesquisa_atleta', methods=['POST'])
def lanca200k_pesquisa_atleta():
    """Pesquisa atleta por número de peito"""
    print("DEBUG: Pesquisando atleta...")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        data = request.get_json()
        km_parcial = data.get('km_parcial')
        nu_peito = data.get('nu_peito')
        
        print(f"DEBUG: Pesquisando atleta - KM: {km_parcial}, Peito: {nu_peito}")
        
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            SELECT 
              i.IDATLETA, CONCAT(i.NUPEITO,' - ',a.NOME,' ',a.SOBRENOME) as NOME,
              COALESCE((SELECT IDEA FROM EQUIPE_ATLETAS WHERE IDATLETA = i.IDATLETA),0) AS IDEA,
              COALESCE((SELECT KM_INI+1 FROM EQUIPE_ATLETAS WHERE IDATLETA = i.IDATLETA),'N') AS KM_INI,
              COALESCE((SELECT KM_FIM FROM EQUIPE_ATLETAS WHERE IDATLETA = i.IDATLETA),'N') AS KM_FIM  
            FROM INSCRICAO i, ATLETA a 
            WHERE a.IDATLETA = i.IDATLETA
              AND (COALESCE((SELECT IDEA FROM EQUIPE_ATLETAS WHERE IDATLETA = i.IDATLETA),0) = 0 
                OR %s BETWEEN COALESCE((SELECT KM_INI+1 FROM EQUIPE_ATLETAS WHERE IDATLETA = i.IDATLETA),'N')
                AND COALESCE((SELECT KM_FIM FROM EQUIPE_ATLETAS WHERE IDATLETA = i.IDATLETA),'N')) 
              AND i.NUPEITO = %s
        """, (km_parcial, nu_peito))
        
        atleta = cursor.fetchone()
        
        if atleta:
            # Verificar se já existe lançamento para este atleta/equipe nesta parcial
            idatleta = atleta[0]
            idea = atleta[2]
            
            # Mapear KM para IDPARCIAL
            km_to_idparcial = {
                25: 2, 50: 3, 75: 4, 100: 5, 
                125: 6, 150: 7, 175: 8, 200: 9
            }
            idparcial = km_to_idparcial.get(int(km_parcial), 0)
            
            # Verificar duplicatas
            if idea == 0:
                # Atleta individual - verificar por IDATLETA
                cursor.execute("""
                    SELECT COUNT(*) FROM PROVA_PARCIAIS_200K 
                    WHERE IDATLETA = %s AND IDPARCIAL = %s
                """, (idatleta, idparcial))
            else:
                # Equipe - verificar por IDEA
                cursor.execute("""
                    SELECT COUNT(*) FROM PROVA_PARCIAIS_200K 
                    WHERE IDEA = %s AND IDPARCIAL = %s
                """, (idea, idparcial))
            
            count = cursor.fetchone()[0]
            cursor.close()
            
            if count > 0:
                if idea == 0:
                    message = f"Atleta já possui lançamento nesta parcial de {km_parcial}km"
                else:
                    message = f"Equipe já possui lançamento nesta parcial de {km_parcial}km"
                
                print(f"DEBUG: Lançamento duplicado detectado: {message}")
                return jsonify({
                    'success': False,
                    'message': message
                })
            
            print(f"DEBUG: Atleta encontrado: {atleta[1]}")
            return jsonify({
                'success': True,
                'atleta': {
                    'IDATLETA': atleta[0],
                    'NOME': atleta[1],
                    'IDEA': atleta[2],
                    'KM_INI': atleta[3],
                    'KM_FIM': atleta[4]
                }
            })
        else:
            cursor.close()
            print("DEBUG: Nenhum atleta encontrado")
            return jsonify({
                'success': False,
                'message': 'Nº de Peito não existe ou Atleta não permitido para esta parcial'
            })
        
    except Exception as e:
        print(f"DEBUG: Erro ao pesquisar atleta: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/lanca200k_confirmar', methods=['POST'])
def lanca200k_confirmar():
    """Confirma o lançamento do atleta"""
    print("DEBUG: Confirmando lançamento...")
    
    if not session.get('autenticado'):
        print("DEBUG: Usuário não autenticado")
        return jsonify({'error': 'Não autenticado'}), 401
    
    try:
        data = request.get_json()
        idea = data.get('idea')
        idatleta = data.get('idatleta')
        data_hora = data.get('data_hora')
        km = data.get('km')
        
        # Mapear KM para IDPARCIAL
        km_to_idparcial = {
            25: 2, 50: 3, 75: 4, 100: 5, 
            125: 6, 150: 7, 175: 8, 200: 9
        }
        
        idparcial = km_to_idparcial.get(int(km), 0)
        
        print(f"DEBUG: Dados para insert - IDEA: {idea}, IDATLETA: {idatleta}, DATA_HORA: {data_hora}, KM: {km}, IDPARCIAL: {idparcial}")
        
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            INSERT INTO PROVA_PARCIAIS_200K (IDEA, IDATLETA, DATA_HORA, IDPARCIAL, KM)
            VALUES (%s, %s, %s, %s, %s)
        """, (idea, idatleta, data_hora, idparcial, km))
        
        mysql.connection.commit()
        cursor.close()
        
        print("DEBUG: Lançamento confirmado com sucesso")
        return jsonify({
            'success': True,
            'message': 'Atleta Lançado com sucesso!'
        })
        
    except Exception as e:
        print(f"DEBUG: Erro ao confirmar lançamento: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
