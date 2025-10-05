# Sincronizador de Atividades Mi Band para Strava

## 🎯 Objetivo

Este projeto contém um script Python para automatizar o processo de upload de atividades físicas registradas em uma Mi Band (através do app Mi Fitness) para o Strava.

Ele foi criado para contornar a falta de integração nativa entre a versão chinesa da Mi Band / Mi Fitness e o Strava, automatizando as seguintes tarefas:

1.  Leitura dos dados de atividades exportados do Mi Fitness em formato `.csv`.
2.  Armazenamento dos registros em um banco de dados local para evitar uploads duplicados.
3.  Autenticação segura com a API do Strava usando OAuth2 (com atualização automática de token).
4.  Upload das novas atividades para o Strava, mapeando os tipos de exercício corretamente.

## ✨ Funcionalidades

-   **Processamento de CSV**: Lê o arquivo `sport_record.csv` exportado pelo Mi Fitness.
-   **Persistência de Dados**: Usa um banco de dados SQL para controlar quais atividades já foram sincronizadas.
-   **Autenticação Robusta**: Gerencia o ciclo de vida completo do token OAuth2 do Strava, incluindo a obtenção inicial e a renovação automática.
-   **Mapeamento de Atividades**: Converte tipos de atividades do Mi Fitness (ex: `indoor_fitness`) para tipos compatíveis com o Strava (ex: `WeightTraining`).
-   **Configuração Segura**: Utiliza um arquivo `.env` para armazenar credenciais e chaves de API de forma segura, fora do código-fonte.

## 🛠️ Tecnologias Utilizadas

-   **Python 3**
-   **Pandas**: Para leitura e manipulação de dados do CSV.
-   **Requests**: Para realizar chamadas à API do Strava.
-   **PyODBC**: Para conexão com o banco de dados (SQL Server).
-   **Python-Dotenv**: Para gerenciamento de variáveis de ambiente.

## 🚀 Como Configurar e Usar

### Pré-requisitos

1.  Python 3.x instalado.
2.  Acesso a um banco de dados SQL (o script está configurado para SQL Server via ODBC, mas pode ser adaptado).
3.  Uma conta de desenvolvedor no Strava para criar uma aplicação API.

### Passos de Configuração

1.  **Clone o repositório:**
    ```bash
    git clone https://[URL_DO_SEU_REPOSITORIO].git
    cd [NOME_DA_PASTA]
    ```

2.  **Crie e ative um ambiente virtual (recomendado):**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Nota: Crie um arquivo `requirements.txt` com o comando `pip freeze > requirements.txt`)*

4.  **Crie sua App no Strava:**
    -   Vá para [Strava API Settings](https://www.strava.com/settings/api).
    -   Crie uma nova aplicação.
    -   Configure o "Authorization Callback Domain" como `localhost`.
    -   Anote seu **Client ID** e **Client Secret**.

5.  **Configure as variáveis de ambiente:**
    -   Renomeie o arquivo `.env.example` para `.env` (ou crie um novo).
    -   Preencha as variáveis com suas informações:
    ```ini
    # .env
    STRAVA_CLIENT_ID=SEU_CLIENT_ID_DO_STRAVA
    STRAVA_CLIENT_SECRET=SEU_CLIENT_SECRET_DO_STRAVA
    DB_CONNECTION_STRING="SUA_STRING_DE_CONEXAO_COM_O_BANCO"
    MI_FITNESS_DOWNLOADS_PATH="C:\Caminho\Para\A\Pasta\De\Exportacao"
    ```

6.  **Prepare o Banco de Dados:**
    -   Execute o script SQL abaixo para criar a tabela `SportRecord` no seu banco de dados:
    ```sql
    CREATE TABLE SportRecord (
        ID INT IDENTITY(1,1) PRIMARY KEY,
        Uid NVARCHAR(255),
        Sid NVARCHAR(255),
        [Key] NVARCHAR(255),
        Time BIGINT,
        Category INT,
        Value NVARCHAR(MAX),
        UpdateTime BIGINT,
        _datahora DATETIME,
        StravaId NVARCHAR(255)
    );
    ```

### Executando o Script

1.  **Exporte seus dados do Mi Fitness** e coloque a pasta de exportação no local definido em `MI_FITNESS_DOWNLOADS_PATH`.

2.  **Rode o script pela primeira vez:**
    ```bash
    python sync_strava.py
    ```
    -   O navegador será aberto para você autorizar o acesso à sua conta Strava.
    -   Após a autorização, um arquivo `strava_tokens.json` será criado.

3.  **Execuções futuras:**
    -   Basta rodar `python sync_strava.py` novamente. O script usará o token salvo e o atualizará se necessário, sem precisar de intervenção no navegador.