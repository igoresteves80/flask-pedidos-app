from flask import Flask, render_template, request, redirect, url_for, session, flash
import oracledb
import os
from datetime import datetime
# hashlib não é mais necessário para a verificação de senha, pois a descriptografia ocorre no DB
# import hashlib

app = Flask(__name__)
# Use uma chave secreta mais robusta em produção
app.secret_key = os.environ.get(
    'SECRET_KEY', 'minha_chave_secreta_padrao_para_desenvolvimento')


def conectar_banco():
    """
    Estabelece uma conexão com o banco de dados Oracle.
    As credenciais e o DSN são obtidos de variáveis de ambiente ou valores padrão.
    """
    try:
        dsn = oracledb.makedsn(
            os.environ.get("DB_HOST", "192.168.12.9"),
            int(os.environ.get("DB_PORT", 1521)),
            service_name=os.environ.get("DB_SERVICE_NAME", "EBAHIANA")
        )
        conn = oracledb.connect(
            user=os.environ.get("DB_USER", "login"),
            password=os.environ.get("DB_PASSWORD", "1234"),
            dsn=dsn
        )
        return conn
    except oracledb.DatabaseError as e:
        # Registra o erro em vez de apenas imprimir, para depuração em produção
        print(f"Erro ao conectar ao banco de dados: {e}")
        raise  # Re-lança a exceção para ser tratada pela função chamadora


def buscar_pedidos(numpedentfut=None, codcli=None, data_inicio=None, data_fim=None, filial=None, numped_cond1=None):
    """
    Busca pedidos no banco de dados Oracle com base nos filtros fornecidos.

    Args:
        numpedentfut (str, optional): Número do pedido.
        codcli (str, optional): Código do cliente.
        data_inicio (str, optional): Data de início do período (formatoYYYY-MM-DD).
        data_fim (str, optional): Data de fim do período (formatoYYYY-MM-DD).
        filial (str, optional): Código da filial.
        numped_cond1 (str, optional): Número do pedido com CONDVENDA = 1.

    Returns:
        list: Uma lista de dicionários, onde cada dicionário representa um pedido.
              Retorna uma lista vazia em caso de erro.
    """
    conn = None
    cursor = None
    try:
        conn = conectar_banco()
        cursor = conn.cursor()

        base_query = """
        SELECT 
            P.NUMPEDENTFUT, 
            P.CODCLI, 
            C.CLIENTE AS NOMECLIENTE, 
            P.VLTOTAL, 
            P.POSICAO,
            P.DATA,
            P.CODFILIAL,
            P.NUMPED,
            P.CONDVENDA
        FROM PCPEDC P
        JOIN PCCLIENT C ON P.CODCLI = C.CODCLI
        WHERE 1=1 -- Cláusula WHERE inicial para facilitar a adição de filtros
        """

        filtros = []
        params = {}

        # Lógica para o novo filtro 'numped_cond1'
        if numped_cond1:
            try:
                numped_cond1_int = int(numped_cond1)
                # Se 'numped_cond1' for fornecido, filtra por NUMPED e CONDVENDA = 1
                filtros.append("P.NUMPED = :numped_cond1 AND P.CONDVENDA = 1")
                params["numped_cond1"] = numped_cond1_int
            except ValueError:
                flash(
                    'Número do Pedido (Condição 1) inválido. Deve ser um número inteiro.', 'danger')
                return []
        else:
            # Se 'numped_cond1' NÃO for fornecido, aplica os filtros padrão de pedidos futuros
            filtros.append("P.CONDVENDA = 8")
            filtros.append("P.POSICAO = 'L'")

        if numpedentfut:
            filtros.append("""
                EXISTS (
                    SELECT 1 FROM PCPEDC PF 
                    WHERE PF.NUMPED = P.NUMPEDENTFUT 
                    AND PF.NUMPED = :numpedentfut
                )
            """)
            params["numpedentfut"] = numpedentfut

        if codcli:
            filtros.append("P.CODCLI = :codcli")
            params["codcli"] = codcli
        if data_inicio:
            try:
                data_inicio_formatada = datetime.strptime(
                    data_inicio, '%Y-%m-%d').date()
                filtros.append("P.DATA >= :data_inicio")
                params["data_inicio"] = data_inicio_formatada
            except ValueError:
                flash(
                    'Formato de data inválido para o início do período. UseYYYY-MM-DD.', 'danger')
                return []
        if data_fim:
            try:
                data_fim_formatada = datetime.strptime(
                    data_fim, '%Y-%m-%d').date()
                filtros.append("P.DATA <= :data_fim")
                params["data_fim"] = data_fim_formatada
            except ValueError:
                flash(
                    'Formato de data inválido para o fim do período. UseYYYY-MM-DD.', 'danger')
                return []

        # Adiciona o filtro de filial APENAS se um valor for fornecido
        if filial:
            try:
                filial_int = int(filial)
                # Ponto de depuração
                print(
                    f"DEBUG: Filial recebida e convertida para int: {filial_int}")
                filtros.append("P.CODFILIAL = :codfilial")
                params["codfilial"] = filial_int
            except ValueError:
                flash('Código da filial inválido. Deve ser um número inteiro.', 'danger')
                return []

        if filtros:
            base_query += " AND " + " AND ".join(filtros)

        base_query += " ORDER BY P.DATA DESC"

        print(f"DEBUG: Executando query: {base_query}")  # Debug
        print(f"DEBUG: Com parâmetros: {params}")  # Debug

        cursor.execute(base_query, params)
        colunas = [desc[0] for desc in cursor.description]
        resultados = cursor.fetchall()

        resultados_dict = []
        for row in resultados:
            row_dict = dict(zip(colunas, row))
            # Formata a data para 'DD/MM/AAAA' antes de enviar para o template
            if 'DATA' in row_dict and isinstance(row_dict['DATA'], datetime):
                row_dict['DATA'] = row_dict['DATA'].strftime('%d/%m/%Y')
            resultados_dict.append(row_dict)

        return resultados_dict
    except oracledb.DatabaseError as e:
        flash(f'Erro no banco de dados ao buscar pedidos: {str(e)}', 'danger')
        return []
    except Exception as e:
        flash(
            f'Ocorreu um erro inesperado ao buscar pedidos: {str(e)}', 'danger')
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def excluir_campos(numped_to_exclude):  # Renomeado o parâmetro
    """
    Define campos específicos como NULL para um pedido, cancelando a separação/conferência.

    Args:
        numped_to_exclude (str): Número do pedido (NUMPED) a ser excluído.
    """
    conn = None
    cursor = None
    try:
        conn = conectar_banco()
        cursor = conn.cursor()

        # Debug
        print(
            f"DEBUG: excluir_campos - Recebido NUMPED para exclusão: {numped_to_exclude}")

        # Removida a SELECT para buscar NUMPED original, pois já recebemos o NUMPED diretamente
        # numped_original = resultado[0] # Esta linha foi removida

        # Campos a serem definidos como NULL
        campos = [
            "NUMVIASMAPASEP", "DTEMISSAOMAPA", "HORAEMISSAOMAPA", "MINUTOEMISSAOMAPA", "CODFUNCEMISSAOMAPA",
            "DTINICIALSEP", "DTFINALSEP", "DTINICIALCHECKOUT", "DTFINALCHECKOUT", "CODFUNCCONF", "CODFUNCSEP"
        ]
        set_clause = ', '.join([f"{campo} = NULL" for campo in campos])
        sql = f"UPDATE PCPEDC SET {set_clause} WHERE NUMPED = :numped"

        # Debug
        print(
            f"DEBUG: excluir_campos - Executando UPDATE: {sql} com numped: {numped_to_exclude}")

        # Usa numped_to_exclude diretamente na query
        cursor.execute(sql, {'numped': numped_to_exclude})
        conn.commit()
        print(f"DEBUG: excluir_campos - Transação COMMITADA com sucesso.")  # Debug
        flash(
            f'Separação e Conferência para o pedido {numped_to_exclude} canceladas com sucesso!', 'success')
    except oracledb.DatabaseError as e:
        # Debug
        print(f"DEBUG: excluir_campos - Erro de banco de dados: {str(e)}")
        flash(f'Erro no banco de dados ao excluir campos: {str(e)}', 'danger')
        conn.rollback()  # Garante que a transação seja desfeita em caso de erro
    except Exception as e:
        print(f"DEBUG: excluir_campos - Erro inesperado: {str(e)}")  # Debug
        flash(
            f'Ocorreu um erro inesperado ao excluir campos: {str(e)}', 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route('/', methods=['GET', 'POST'])
def index():
    """
    Rota principal para exibir e filtrar pedidos.
    Requer autenticação de usuário.
    """
    if 'usuario' not in session:
        return redirect(url_for('login'))

    result = None
    form_data = {
        'numped': '',
        'codcli': '',
        'data_inicio': '',
        'data_fim': '',
        'filial': '',
        'numped_cond1': ''  # Adicionado o novo campo ao form_data
    }

    if request.method == 'POST':
        if 'excluir' in request.form:
            # Lógica para exclusão de campos
            # Passa o valor de 'excluir' (que agora é o NUMPED) diretamente
            excluir_campos(request.form.get('excluir'))
            # Redireciona para GET para evitar reenvio do formulário
            return redirect(url_for('index'))
        else:
            # Lógica para filtragem de pedidos
            form_data = {
                'numped': request.form.get('numped', ''),
                'codcli': request.form.get('codcli', ''),
                'data_inicio': request.form.get('data_inicio', ''),
                'data_fim': request.form.get('data_fim', ''),
                'filial': request.form.get('filial', ''),
                # Obtém o valor do novo campo
                'numped_cond1': request.form.get('numped_cond1', '')
            }

            # Debug
            print(
                f"DEBUG: Filtros recebidos -> numped: {form_data['numped']}, codcli: {form_data['codcli']}, data_inicio: {form_data['data_inicio']}, data_fim: {form_data['data_fim']}, filial: {form_data['filial']}, numped_cond1: {form_data['numped_cond1']}")

            result = buscar_pedidos(
                form_data['numped'],
                form_data['codcli'],
                form_data['data_inicio'],
                form_data['data_fim'],
                form_data['filial'],
                form_data['numped_cond1']  # Passa o novo valor para a função
            )

            if result:
                flash(
                    f'Foram encontrados {len(result)} pedidos com os filtros aplicados.', 'info')
            else:
                flash('Nenhum pedido encontrado com os filtros aplicados.', 'info')

    # Passa o nome de usuário da sessão para o template
    # Se 'usuario' não estiver na sessão, usa 'Convidado' como padrão
    usuario_logado = session.get('usuario', 'Convidado')
    return render_template('index.html', result=result, form_data=form_data, usuario=usuario_logado)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Rota para a página de login. Autentica o utilizador contra a base de dados PCEMPR usando a matrícula.
    """
    if request.method == 'POST':
        # Obtém a matrícula e senha do formulário
        matricula_digitada = request.form['matricula']
        senha_digitada = request.form['senha']

        conn = None
        cursor = None
        try:
            conn = conectar_banco()
            cursor = conn.cursor()

            # Atualizando a consulta para usar o nome correto do campo 'CODSETOR'
            query = """
            SELECT USUARIOBD, decrypt(SENHABD, USUARIOBD) AS SENHA_DESCRIPTOGRAFADA, CODPERFIL, CODSETOR
            FROM PCEMPR
            WHERE MATRICULA = :matricula_digitada
            """
            print(f"DEBUG: Executando query para matrícula {matricula_digitada}")  # Debug
            # Passa a matrícula como parâmetro
            cursor.execute(query, {'matricula_digitada': matricula_digitada})

            resultado = cursor.fetchone()

            if resultado:
                # USUARIOBD (primeira coluna do SELECT)
                usuario_db = resultado[0]
                # SENHA_DESCRIPTOGRAFADA (segunda coluna do SELECT)
                senha_descriptografada_db = resultado[1]
                # CODPERFIL (terceira coluna do SELECT)
                codperfil_db = resultado[2]
                # CODSETOR (quarta coluna do SELECT, agora corrigido)
                codsetor_db = resultado[3]

                # Debug para verificar os valores recebidos
                print(f"DEBUG: Usuário DB: {usuario_db}, Senha DB: {senha_descriptografada_db}, CODPERFIL: {codperfil_db}, CODSETOR: {codsetor_db}")

                # Compara a senha digitada diretamente com a senha descriptografada do DB
                if senha_digitada == senha_descriptografada_db:
                    # Certifica-se de que ambos os valores são inteiros para evitar comparações incorretas
                    if isinstance(codperfil_db, str):
                        codperfil_db = int(codperfil_db)  # Converte para inteiro se necessário
                    if isinstance(codsetor_db, str):
                        codsetor_db = int(codsetor_db)  # Converte para inteiro se necessário

                    # Verifica se CODPERFIL é 32 ou CODSETOR é 9
                    if codperfil_db == 32 or codsetor_db == 9:
                        # Armazena o USUARIOBD na sessão
                        session['usuario'] = usuario_db
                        flash('Login realizado com sucesso!', 'success')
                        return redirect(url_for('index'))
                    else:
                        flash('Você não tem permissão para acessar a aplicação.', 'danger')
                        return redirect(url_for('login'))
                else:
                    print("DEBUG: Senha incorreta.")
                    flash('Credenciais inválidas. Tente novamente.', 'danger')
            else:
                print(f"DEBUG: Matrícula '{matricula_digitada}' não encontrada.")
                flash('Credenciais inválidas. Tente novamente.', 'danger')

        except oracledb.DatabaseError as e:
            print(f"Erro no banco de dados durante o login: {str(e)}")
            flash(f'Erro no banco de dados durante o login: {str(e)}', 'danger')
        except Exception as e:
            print(f"Erro inesperado durante o login: {str(e)}")
            flash(f'Ocorreu um erro inesperado durante o login: {str(e)}', 'danger')
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    return render_template('login.html')





@app.route('/logout')
def logout():
    """
    Rota para realizar o logout do usuário.
    """
    session.clear()
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('login'))


if __name__ == '__main__':
    # Configurações para execução local
    # Alterado para '0.0.0.0' para ser acessível externamente na rede local
    app.run(host='0.0.0.0', port=5000, debug=True)
