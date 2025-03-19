from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
import os
from flask_mysqldb import MySQL
import uuid
import base64
from datetime import datetime
import boto3
from botocore.exceptions import NoCredentialsError

app = Flask(__name__)

# Configuração do MySQL
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')
mysql = MySQL(app)

# Configuração do S3
S3_BUCKET = os.getenv('S3_BUCKET_NAME')
S3_REGION = os.getenv('AWS_REGION', 'us-east-1')
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('AWS_SECRET_KEY'),
    region_name=S3_REGION
)

# Função para gerar URL do S3
def get_s3_url(file_name):
    return f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{file_name}"

# Configuração para diretório temporário
TEMP_FOLDER = '/tmp'
app.secret_key = os.getenv('SECRET_KEY', 'chave_secreta_padrao')

# Função para fazer upload para o S3
def upload_to_s3(file_path, object_name):
    try:
        s3_client.upload_file(file_path, S3_BUCKET, object_name)
        return get_s3_url(object_name)
    except NoCredentialsError:
        return None
    except Exception as e:
        print(f"Erro ao fazer upload para S3: {str(e)}")
        return None

# Função para fazer upload de dados de imagem base64 para o S3
def upload_base64_to_s3(base64_data, object_name):
    try:
        # Remover o prefixo da string base64
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]
        
        # Decode base64 para bytes
        image_bytes = base64.b64decode(base64_data)
        
        # Upload para S3
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=object_name,
            Body=image_bytes,
            ContentType='image/jpeg'
        )
        
        return get_s3_url(object_name)
    except Exception as e:
        print(f"Erro ao fazer upload base64 para S3: {str(e)}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/nova_vistoria')
def nova_vistoria():
    # Busca motoristas e veículos do banco de dados
    cur = mysql.connection.cursor()
    cur.execute("SELECT IDMOTORISTA, NOME FROM MOTORISTAS")
    motoristas = cur.fetchall()
    cur.execute("SELECT IDVEICULO, PLACA FROM VEICULOS")
    veiculos = cur.fetchall()
    cur.close()
    
    return render_template('nova_vistoria.html', motoristas=motoristas, veiculos=veiculos, tipo='ENTREGA')

@app.route('/nova_vistoria_devolucao/<int:vistoria_entrega_id>')
def nova_vistoria_devolucao(vistoria_entrega_id):
    # Buscar informações da vistoria de entrega
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT v.IDVISTORIA, v.IDMOTORISTA, v.IDVEICULO, m.NOME, ve.PLACA
        FROM VISTORIAS v
        JOIN MOTORISTAS m ON v.IDMOTORISTA = m.IDMOTORISTA
        JOIN VEICULOS ve ON v.IDVEICULO = ve.IDVEICULO
        WHERE v.IDVISTORIA = %s AND v.TIPO = 'ENTREGA'
    """, (vistoria_entrega_id,))
    vistoria_entrega = cur.fetchone()
    cur.close()
    
    if not vistoria_entrega:
        flash('Vistoria de entrega não encontrada!', 'danger')
        return redirect(url_for('vistorias'))
    
    return render_template(
        'nova_vistoria.html', 
        motorista_id=vistoria_entrega[1],
        motorista_nome=vistoria_entrega[3],
        veiculo_id=vistoria_entrega[2],
        veiculo_placa=vistoria_entrega[4],
        vistoria_entrega_id=vistoria_entrega_id,
        tipo='DEVOLUCAO'
    )

@app.route('/salvar_vistoria', methods=['POST'])
def salvar_vistoria():
    try:
        # Obter dados do formulário
        id_motorista = request.form['id_motorista']
        id_veiculo = request.form['id_veiculo']
        tipo = request.form['tipo']
        vistoria_entrega_id = request.form.get('vistoria_entrega_id')
        
        # Criar uma nova vistoria
        cur = mysql.connection.cursor()
        
        if tipo == 'ENTREGA':
            cur.execute(
                "INSERT INTO VISTORIAS (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS) VALUES (%s, %s, NOW(), 'ENTREGA', 'EM_TRANSITO')",
                (id_motorista, id_veiculo)
            )
        else:  # DEVOLUCAO
            # Inserir vistoria de devolução
            cur.execute(
                "INSERT INTO VISTORIAS (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS, VISTORIA_ENTREGA_ID) VALUES (%s, %s, NOW(), 'DEVOLUCAO', 'FINALIZADA', %s)",
                (id_motorista, id_veiculo, vistoria_entrega_id)
            )
            # Atualizar status da vistoria de entrega para finalizada
            cur.execute(
                "UPDATE VISTORIAS SET STATUS = 'FINALIZADA' WHERE IDVISTORIA = %s",
                (vistoria_entrega_id,)
            )
            
        mysql.connection.commit()
        
        # Obter o ID da vistoria criada
        id_vistoria = cur.lastrowid
        
        # Processar as fotos da vistoria
        fotos = request.files.getlist('fotos[]')
        detalhamentos = request.form.getlist('detalhamentos[]')
        
        for i, foto in enumerate(fotos):
            if foto and foto.filename:
                # Gerar nome de arquivo único
                filename = f"vistoria_{id_vistoria}_{uuid.uuid4()}.jpg"
                s3_object_name = f"uploads/{filename}"
                
                # Salvar temporariamente o arquivo
                temp_path = os.path.join(TEMP_FOLDER, filename)
                foto.save(temp_path)
                
                # Fazer upload para o S3
                s3_url = upload_to_s3(temp_path, s3_object_name)
                
                # Remover arquivo temporário
                os.remove(temp_path)
                
                detalhamento = detalhamentos[i] if i < len(detalhamentos) else ""
                
                # Inserir na tabela VISTORIA_ITENS com a URL do S3
                cur.execute(
                    "INSERT INTO VISTORIA_ITENS (IDVISTORIA, FOTO, DETALHAMENTO) VALUES (%s, %s, %s)",
                    (id_vistoria, s3_url, detalhamento)
                )
                mysql.connection.commit()
        
        cur.close()
        flash('Vistoria salva com sucesso!', 'success')
        return redirect(url_for('vistorias'))
    
    except Exception as e:
        flash(f'Erro ao salvar vistoria: {str(e)}', 'danger')
        return redirect(url_for('nova_vistoria'))

@app.route('/salvar_foto', methods=['POST'])
def salvar_foto():
    try:
        data = request.json
        image_data = data['image_data']
        
        # Gerar um nome de arquivo único
        filename = f"temp_{uuid.uuid4()}.jpg"
        s3_object_name = f"uploads/{filename}"
        
        # Fazer upload direto para o S3
        s3_url = upload_base64_to_s3(image_data, s3_object_name)
        
        if s3_url:
            return jsonify({'success': True, 'filename': filename, 's3_url': s3_url})
        else:
            return jsonify({'success': False, 'error': 'Falha ao fazer upload para S3'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/vistorias')
def listar_vistorias():
    cur = mysql.connection.cursor()
    
    # Buscar vistorias em trânsito (Entregas não finalizadas)
    cur.execute("""
        SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA, v.TIPO, v.STATUS 
        FROM VISTORIAS v
        JOIN MOTORISTAS m ON v.IDMOTORISTA = m.IDMOTORISTA
        JOIN VEICULOS ve ON v.IDVEICULO = ve.IDVEICULO
        WHERE v.STATUS = 'EM_TRANSITO'
        ORDER BY v.DATA DESC
    """)
    vistorias_em_transito = cur.fetchall()
    
    # Buscar vistorias finalizadas (Entregas com devolução ou devoluções)
    cur.execute("""
        SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA, v.TIPO, v.STATUS 
        FROM VISTORIAS v
        JOIN MOTORISTAS m ON v.IDMOTORISTA = m.IDMOTORISTA
        JOIN VEICULOS ve ON v.IDVEICULO = ve.IDVEICULO
        WHERE v.STATUS = 'FINALIZADA'
        ORDER BY v.DATA DESC
    """)
    vistorias_finalizadas = cur.fetchall()
    
    cur.close()
    
    return render_template(
        'vistorias.html', 
        vistorias_em_transito=vistorias_em_transito,
        vistorias_finalizadas=vistorias_finalizadas
    )

@app.route('/vistoria/<int:id>')
def ver_vistoria(id):
    cur = mysql.connection.cursor()
    
    # Buscar detalhes da vistoria
    cur.execute("""
        SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA, v.TIPO, v.STATUS,
               v.VISTORIA_ENTREGA_ID
        FROM VISTORIAS v
        JOIN MOTORISTAS m ON v.IDMOTORISTA = m.IDMOTORISTA
        JOIN VEICULOS ve ON v.IDVEICULO = ve.IDVEICULO
        WHERE v.IDVISTORIA = %s
    """, (id,))
    vistoria = cur.fetchone()
    
    # Se for uma vistoria de devolução, buscar também a vistoria de entrega
    vistoria_entrega = None
    if vistoria and vistoria[4] == 'DEVOLUCAO' and vistoria[6]:
        cur.execute("""
            SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA
            FROM VISTORIAS v
            JOIN MOTORISTAS m ON v.IDMOTORISTA = m.IDMOTORISTA
            JOIN VEICULOS ve ON v.IDVEICULO = ve.IDVEICULO
            WHERE v.IDVISTORIA = %s
        """, (vistoria[6],))
        vistoria_entrega = cur.fetchone()
    
    # Se for uma vistoria de entrega, buscar se já existe uma vistoria de devolução
    vistoria_devolucao = None
    if vistoria and vistoria[4] == 'ENTREGA':
        cur.execute("""
            SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA
            FROM VISTORIAS v
            JOIN MOTORISTAS m ON v.IDMOTORISTA = m.IDMOTORISTA
            JOIN VEICULOS ve ON v.IDVEICULO = ve.IDVEICULO
            WHERE v.VISTORIA_ENTREGA_ID = %s
        """, (id,))
        vistoria_devolucao = cur.fetchone()
    
    # Buscar fotos e detalhamentos da vistoria
    cur.execute("""
        SELECT FOTO, DETALHAMENTO
        FROM VISTORIA_ITENS
        WHERE IDVISTORIA = %s
    """, (id,))
    itens = cur.fetchall()
    cur.close()
    
    return render_template(
        'ver_vistoria.html', 
        vistoria=vistoria, 
        itens=itens,
        vistoria_entrega=vistoria_entrega,
        vistoria_devolucao=vistoria_devolucao
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
