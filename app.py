from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
from flask_mysqldb import MySQL
import uuid
import base64
from datetime import datetime

app = Flask(__name__)

# Configuração do MySQL
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')
mysql = MySQL(app)

# Configuração para armazenar fotos
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = os.getenv('SECRET_KEY', 'chave_secreta_padrao')

# Certifique-se de que a pasta de uploads existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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
                filename = f"vistoria_{id_vistoria}_{uuid.uuid4()}.jpg"
                foto_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                foto.save(foto_path)
                
                detalhamento = detalhamentos[i] if i < len(detalhamentos) else ""
                
                # Inserir na tabela VISTORIA_ITENS
                cur.execute(
                    "INSERT INTO VISTORIA_ITENS (IDVISTORIA, FOTO, DETALHAMENTO) VALUES (%s, %s, %s)",
                    (id_vistoria, filename, detalhamento)
                )
                mysql.connection.commit()
        
        cur.close()
        flash('Vistoria salva com sucesso!', 'success')
        return redirect(url_for('index'))  # Modificado para redirecionar para index.html
    
    except Exception as e:
        flash(f'Erro ao salvar vistoria: {str(e)}', 'danger')
        return redirect(url_for('nova_vistoria'))
        
@app.route('/salvar_foto', methods=['POST'])
def salvar_foto():
    try:
        data = request.json
        image_data = data['image_data']
        
        # Remover o prefixo da string base64
        image_data = image_data.split(',')[1]
        
        # Gerar um nome de arquivo único
        filename = f"temp_{uuid.uuid4()}.jpg"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Salvar a imagem
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(image_data))
        
        return jsonify({'success': True, 'filename': filename})
    
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
