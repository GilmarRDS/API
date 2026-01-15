Aqui estão os arquivos essenciais para o seu projeto.

O .gitignore é fundamental agora que você está mexendo com credenciais do Google, pois ele impede que o arquivo secrets.toml (onde está sua senha) seja enviado para o GitHub ou compartilhado acidentalmente.

1. Arquivo .gitignore
Crie um arquivo chamado .gitignore (exatamente assim, começando com ponto e sem extensão) na raiz da sua pasta e cole o seguinte:

Snippet de código

# Byte-compiled / otimização do Python
__pycache__/
*.py[cod]
*$py.class

# Ambientes Virtuais (se você usar venv)
venv/
env/
.env

# --- SEGURANÇA STREAMLIT (CRÍTICO) ---
# Ignora o arquivo que contém sua chave privada do Google
.streamlit/secrets.toml

# --- Arquivos de Dados Locais ---
# Ignora planilhas geradas ou bancos de dados locais antigos
*.xlsx
*.xls
*.csv

# Logs e arquivos de sistema
*.log
.DS_Store

# Configurações de IDE (VS Code, Pycharm)
.vscode/
.idea/
2. Arquivo README.md
Este arquivo serve como a capa e o manual de instruções do seu projeto. Crie um arquivo chamado README.md e cole isso:

Markdown

# 🎓 Gestor Escolar - Sistema de Horários

Sistema desenvolvido em Python com Streamlit para gestão de turmas, currículos, professores e geração automática de horários escolares, integrado ao Google Sheets para armazenamento em nuvem.

## 🚀 Funcionalidades

* **Gestão de Turmas:** Cadastro de turmas de Educação Infantil e Fundamental.
* **Currículo Flexível:** Definição de matérias por ano/etapa.
* **Banco de Professores:** Cadastro de docentes, carga horária e especialidades.
* **Gerador de Horários:** Algoritmo que distribui aulas automaticamente respeitando a disponibilidade.
* **Nuvem:** Todos os dados são salvos e lidos diretamente do Google Sheets.

## 🛠️ Instalação

1. Clone o repositório ou baixe os arquivos.
2. Crie um ambiente virtual (opcional, mas recomendado):
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
Instale as dependências:

Bash

pip install -r requirements.txt
⚙️ Configuração (Google Sheets)
Para que o sistema funcione, é necessário configurar as credenciais de acesso:

Crie uma pasta .streamlit na raiz do projeto.

Crie um arquivo secrets.toml dentro dessa pasta.

O conteúdo deve seguir este formato (obtenha seus dados no Google Cloud Console):

Ini, TOML

[connections.gsheets]
spreadsheet = "LINK_DA_SUA_PLANILHA_GOOGLE"
type = "service_account"
project_id = "seu-project-id"
private_key_id = "sua-key-id"
private_key = "-----BEGIN PRIVATE KEY-----\n..."
client_email = "seu-bot-email@..."
client_id = "seu-client-id"
# ... outros campos do JSON
Atenção: Nunca compartilhe o arquivo secrets.toml publicamente.

▶️ Como Executar
No terminal, execute:

Bash

streamlit run app.py
O sistema abrirá automaticamente no seu navegador.

📋 Estrutura da Planilha
O sistema espera que a planilha do Google Sheets tenha as seguintes abas (guias):

Turmas

Curriculo

Professores

---

### Bônus: `requirements.txt`
Para que o passo de instalação do README funcione, crie também um arquivo chamado `requirements.txt` com as bibliotecas que usamos:

```text
streamlit
streamlit-gsheets
pandas
xlsxwriter
st-connection