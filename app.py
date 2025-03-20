from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
import os
from flask_mysqldb import MySQL
import uuid
import base64
from datetime import datetime
from io import BytesIO

app = Flask(__name__)

# Configuração do MySQL
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')
mysql = MySQL(app)

# Configuração para segurança
app.secret_key = os.getenv('SECRET_KEY')

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
            # Capturar o último ID antes da inserção
            cur.execute("SELECT MAX(IDVISTORIA) FROM VISTORIAS")
            ultimo_id = cur.fetchone()[0] or 0
            
            cur.execute(
                "INSERT INTO VISTORIAS (IDMOTORISTA, IDVEICULO, DATA, TIPO, STATUS) VALUES (%s, %s, NOW(), 'ENTREGA', 'EM_TRANSITO')",
                (id_motorista, id_veiculo)
            )
        else:  # DEVOLUCAO
            # Capturar o último ID antes da inserção
            cur.execute("SELECT MAX(IDVISTORIA) FROM VISTORIAS")
            ultimo_id = cur.fetchone()[0] or 0
            
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
                        "INSERT INTO VISTORIA_ITENS (IDVISTORIA, FOTO, DETALHAMENTO) VALUES (%s, %s, %s)",
                        (id_vistoria, foto_data, detalhamento)
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
        SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA, v.TIPO, v.STATUS, v.COMBUSTIVEL,
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
            SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA, v.COMBUSTIVEL
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
            SELECT v.IDVISTORIA, m.NOME as MOTORISTA, ve.PLACA, v.DATA, v.COMBUSTIVEL
            FROM VISTORIAS v
            JOIN MOTORISTAS m ON v.IDMOTORISTA = m.IDMOTORISTA
            JOIN VEICULOS ve ON v.IDVEICULO = ve.IDVEICULO
            WHERE v.VISTORIA_ENTREGA_ID = %s
        """, (id,))
        vistoria_devolucao = cur.fetchone()
    
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
        'ver_vistoria.html', 
        vistoria=vistoria, 
        itens=itens,
        vistoria_entrega=vistoria_entrega,
        vistoria_devolucao=vistoria_devolucao
    )


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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
