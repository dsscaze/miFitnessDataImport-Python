import os
import json
import requests
import pandas as pd
import pyodbc
from dotenv import load_dotenv
from datetime import datetime, timedelta
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
import re
import glob

# Carrega as variáveis do arquivo .env
load_dotenv()

# --- Configurações ---
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
DB_CONNECTION_STRING = os.getenv("DB_CONNECTION_STRING")
MI_FITNESS_DOWNLOADS_PATH = os.getenv("MI_FITNESS_DOWNLOADS_PATH")
TOKEN_FILE = "strava_tokens.json"

# --- 1. Autenticação com Strava (A parte mais complexa) ---

def get_strava_token():
    """Gerencia o token do Strava, atualizando-o se necessário."""
    
    # Verifica se o arquivo de token já existe
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            tokens = json.load(f)
        
        # Se o token expirou, atualiza usando o refresh_token
        if tokens['expires_at'] < datetime.now().timestamp():
            print("Token do Strava expirado. Atualizando...")
            response = requests.post(
                "https://www.strava.com/oauth/token",
                data={
                    'client_id': STRAVA_CLIENT_ID,
                    'client_secret': STRAVA_CLIENT_SECRET,
                    'grant_type': 'refresh_token',
                    'refresh_token': tokens['refresh_token']
                }
            )
            response.raise_for_status()
            new_tokens = response.json()
            with open(TOKEN_FILE, 'w') as f:
                json.dump(new_tokens, f)
            print("Token atualizado com sucesso.")
            return new_tokens['access_token']
        else:
            print("Token do Strava ainda é válido.")
            return tokens['access_token']
    else:
        # Se for a primeira vez, executa o fluxo de autorização completo
        return first_time_auth()

def first_time_auth():
    """Executa o fluxo de autorização inicial via navegador."""
    print("Primeira autenticação. Por favor, autorize o acesso no seu navegador.")
    
    auth_url = (f"http://www.strava.com/oauth/authorize?client_id={STRAVA_CLIENT_ID}"
                f"&response_type=code&redirect_uri=http://localhost:8000"
                f"&approval_prompt=force&scope=activity:write,activity:read")

    webbrowser.open(auth_url)
    
    # Inicia um servidor web local para capturar o código de autorização
    # (o Strava vai redirecionar para http://localhost:8000 com o código)
    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h1>Autorizacao recebida! Pode fechar esta janela.</h1>")
            
            # Extrai o código da URL
            code = self.path.split('code=')[1].split('&')[0]
            self.server.auth_code = code

    server_address = ('', 8000)
    with HTTPServer(server_address, RequestHandler) as httpd:
        print("Aguardando autorização do usuário no navegador...")
        httpd.handle_request() # Processa uma única requisição e para
    
    auth_code = httpd.auth_code
    print("Código de autorização recebido.")

    # Troca o código pelo token de acesso e refresh token
    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            'client_id': STRAVA_CLIENT_ID,
            'client_secret': STRAVA_CLIENT_SECRET,
            'code': auth_code,
            'grant_type': 'authorization_code'
        }
    )
    response.raise_for_status()
    tokens = response.json()

    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f)
    
    print("Tokens salvos em strava_tokens.json.")
    return tokens['access_token']

def process_csv_to_db(csv_path):
    """Lê o CSV, verifica duplicados no DB e insere novos registros."""
    if not csv_path:
        return
        
    print(f"Processando arquivo CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    
    try:
        conn = pyodbc.connect(DB_CONNECTION_STRING)
        cursor = conn.cursor()
        
        new_records_count = 0
        for index, row in df.iterrows():
            # Verifica se o registro já existe
            cursor.execute("""
                SELECT 1 FROM sportrecord 
                WHERE [key] = ? AND time = ? AND value = ?
            """, (row['Key'], row['Time'], row['Value']))
            
            if cursor.fetchone() is None:
                # Insere o novo registro
                cursor.execute("""
                    INSERT INTO sportrecord (Uid, Sid, [Key], Time, Category, Value, UpdateTime)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (row['Uid'], row['Sid'], row['Key'], row['Time'], row['Category'], row['Value'], row['UpdateTime']))
                
                # Atualiza o campo de data/hora (equivalente ao seu segundo comando)
                # O fuso -3h está aqui
                cursor.execute("""
                    UPDATE SportRecord 
                    SET _datahora = dateadd(hour, -3, DATEADD(s, cast([time] as int), '1970-01-01 00:00:00')) 
                    WHERE [Key] = ? AND time = ? AND _datahora IS NULL
                """, (row['Key'], row['Time']))
                
                new_records_count += 1

        conn.commit()
        print(f"Processamento do CSV concluído. {new_records_count} novos registros inseridos no banco de dados.")
    
    except Exception as e:
        print(f"Erro ao processar o CSV para o banco de dados: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

# --- 3. Sincronização de Atividades para o Strava ---

def upload_activities_to_strava(access_token):
    """Busca atividades não sincronizadas do DB e as envia para o Strava."""
    print("\nIniciando sincronização de atividades para o Strava...")
    
    # Mapeamento de atividades Mi Fitness para Strava
    activity_map = {
        "indoor_running": ("VirtualRun", "esteira"),
        "indoor_walking": ("Walk", "caminhada na esteira"),
        "indoor_fitness": ("WeightTraining", "musculação"),
        "climbing_machine": ("StairStepper", "escada"),
        "elliptical_trainer": ("Elliptical", "eliptico"),
        "outdoor_running": ("Run", "corrida"),
        "volleyball": ("Workout", "Vôlei")
    }
    
    try:
        conn = pyodbc.connect(DB_CONNECTION_STRING)
        cursor = conn.cursor()

        # Busca atividades a partir de uma data, que não foram enviadas e não são 'outdoor'
        cursor.execute("""
            SELECT id, [value], [key], _datahora
            FROM SportRecord
            WHERE _datahora >= '2024-06-01'
            AND StravaId IS NULL
            AND [key] NOT LIKE 'outdoor%'
        """)
        
        activities_to_upload = cursor.fetchall()
        print(f"Encontradas {len(activities_to_upload)} atividades para enviar ao Strava.")

        for activity in activities_to_upload:
            id_db, value_json, key, start_time = activity
            
            if key not in activity_map:
                print(f"Atividade com key '{key}' não mapeada. Pulando.")
                continue

            sport_type, name = activity_map[key]
            
            try:
                data = json.loads(value_json)
                duration = int(data.get('duration', 0))
                distance = int(data.get('distance', 0))
                
                # Formata a data para o padrão ISO 8601 exigido pelo Strava
                start_date_local = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')

                payload = {
                    "name": name,
                    "type": sport_type,
                    "sport_type": sport_type,
                    "start_date_local": start_date_local,
                    "elapsed_time": duration,
                    "description": "Sincronizado via Mi Band Python Sync",
                    "distance": distance
                }
                
                headers = {'Authorization': f'Bearer {access_token}'}
                
                print(f"Enviando atividade: {name} de {start_date_local}")
                response = requests.post("https://www.strava.com/api/v3/activities", headers=headers, data=payload)
                response.raise_for_status() # Lança um erro se a requisição falhar
                
                strava_activity = response.json()
                strava_id = strava_activity['id']
                print(f"Atividade criada no Strava com ID: {strava_id}")

                # Atualiza o banco de dados com o ID do Strava
                cursor.execute("UPDATE SportRecord SET StravaId = ? WHERE id = ?", (str(strava_id), id_db))
                conn.commit()
                
                # [Opcional] Oculta a atividade da home, como no seu código original
                update_payload = {'hide_from_home': True}
                update_url = f"https://www.strava.com/api/v3/activities/{strava_id}"
                requests.put(update_url, headers=headers, json=update_payload)
                print(f"Atividade {strava_id} ocultada do feed inicial.")

            except Exception as e:
                print(f"Erro ao processar a atividade ID {id_db}: {e}")
                # Aqui você pode adicionar um log de erro mais robusto
    
    except Exception as e:
        print(f"Erro ao conectar com o banco de dados para upload: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()
            
    print("Sincronização com Strava concluída.")

def get_sport_csv_path(export_folder_path):
    """
    Constrói o caminho para o arquivo CSV de esporte dentro da pasta de exportação fornecida.
    O nome do arquivo é derivado do nome da pasta.
    """
    if not os.path.isdir(export_folder_path):
        print(f"Erro: A pasta especificada não existe -> '{export_folder_path}'")
        return None

    # Extrai o nome base da pasta (ex: "20251005_6599729986_MiFitness_c3_data_copy")
    folder_name = os.path.basename(export_folder_path)
    
    # Remove o sufixo "_c3_data_copy" para construir o nome do arquivo
    file_prefix = folder_name.replace("_c3_data_copy", "")
    
    # Monta o nome completo do arquivo CSV
    csv_filename = f"{file_prefix}_hlth_center_sport_record.csv"
    
    # Monta o caminho completo do arquivo
    full_csv_path = os.path.join(export_folder_path, csv_filename)
    
    if not os.path.exists(full_csv_path):
        print(f"Erro: O arquivo CSV esperado não foi encontrado em -> '{full_csv_path}'")
        return None
        
    print(f"Arquivo CSV a ser processado: {full_csv_path}")
    return full_csv_path

# --- Execução Principal ---
if __name__ == "__main__":
    print("--- INICIANDO SINCRONIZADOR MI BAND -> STRAVA ---")
    
    # 1. Processa o CSV para o banco de dados
    target_csv_path = get_sport_csv_path(MI_FITNESS_DOWNLOADS_PATH)
    process_csv_to_db(target_csv_path)
    
    # 2. Obtém um token válido do Strava
    token = get_strava_token()
    
    # 3. Envia as atividades pendentes para o Strava
    upload_activities_to_strava(token)
    
    print("\n--- PROCESSO FINALIZADO ---")