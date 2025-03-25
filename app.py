import os
import tempfile
import requests
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify, session
from bs4 import BeautifulSoup
from langchain.memory import ConversationBufferMemory
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek
from docx import Document
import pandas as pd
from dotenv import load_dotenv
import validators
import io
import PyPDF2
import warnings
from datetime import datetime
import re
import json

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Inicializa o Flask
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'  # Altere para uma chave segura

# Limite de tamanho das requisições (50 MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

# Carrega variáveis de ambiente
load_dotenv("config.env")
os.environ['USER_AGENT'] = 'AssistenteApp/1.0'

# Carrega a senha de configuração
CONFIG_PASSWORD = os.getenv('CONFIG_PASSWORD', '')  # Senha padrão

# Carrega a api use de configuração
API_USE = os.getenv('API_USE')

# Configuração dos modelos com limites de max_tokens por provedor
CONFIG_MODELOS = {
    'DeepSeek': {
        'modelos': ['deepseek-reasoner', 'deepseek-chat'],
        'chat': ChatDeepSeek,
        'max_tokens_limit': 8192
    },
    'OpenAI': {
        'modelos': ['gpt-4o-mini', 'gpt-4o', 'o1-preview', 'o1-mini'],
        'chat': ChatOpenAI,
        'max_tokens_limit': 4096
    },
    'Groq': {
        'modelos': ['llama-3.1-70b-versatile', 'gemma2-9b-it', 'mixtral-8x7b-32768'],
        'chat': ChatGroq,
        'max_tokens_limit': 32768
    }
}

# Dicionário de prompts por especialidade
PROMPTS_ESPECIALIDADES = {
    "D. Administrativo": """Você é um assistente virtual especializado em Direito Administrativo, com amplo conhecimento em legislação, jurisprudência, doutrina e práticas relacionadas ao direito público no Brasil. Sua função é fornecer informações precisas, claras e atualizadas sobre temas como licitações, contratos administrativos, servidores públicos, improbidade administrativa, processos administrativos, controle da administração pública, entre outros.

Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos.

Além disso, esteja preparado para:
- Analisar casos concretos e sugerir possíveis soluções com base na legislação vigente.
- Esclarecer dúvidas sobre prazos, procedimentos e recursos administrativos.
- Orientar sobre os direitos e deveres dos cidadãos em relação à administração pública.
- Fornecer modelos de petições, recursos ou documentos administrativos, quando solicitado.

Sua linguagem deve ser formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada ao Direito Administrativo, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte.""",
    "D. Penal": """Você é um assistente virtual especializado em Direito Penal, com domínio da legislação penal brasileira, jurisprudência, doutrina e princípios do direito criminal. Responda com precisão sobre crimes, penas, processos penais, medidas cautelares, execução penal e garantias constitucionais, citando sempre o Código Penal, a Constituição e decisões relevantes do STF e STJ.""",
    "P. Penal": """Você é um assistente virtual especializado em Processo Penal, com expertise no Código de Processo Penal brasileiro. Forneça informações detalhadas sobre fases do processo, recursos, prazos, provas, audiências e direitos processuais, baseando-se em leis e jurisprudências do STF e STJ.""",
    "D. Cívil": """Você é um assistente virtual especializado em Direito Civil, com conhecimento profundo do Código Civil brasileiro, contratos, responsabilidade civil, direitos reais, família e sucessões. Responda com base legal e jurisprudencial, adaptando-se ao público.""",
    "P. Cívil": """Você é um assistente virtual especializado em Processo Civil, com domínio do Código de Processo Civil brasileiro. Oriente sobre procedimentos, prazos, recursos, petições e execução, citando leis e jurisprudências relevantes.""",
    "D. Consumidor": """Você é um assistente virtual especializado em Direito do Consumidor, com base no Código de Defesa do Consumidor (CDC). Responda sobre relações de consumo, direitos do consumidor, contratos, práticas abusivas e ações judiciais, citando o CDC e jurisprudências.""",
    "D. Tributário": """Você é um assistente virtual especializado em Direito Tributário, com conhecimento em tributos, impostos, taxas, contribuições e processos fiscais no Brasil. Baseie-se no Código Tributário Nacional, leis específicas e decisões do STF e STJ."""
}

# Carrega configurações do config.env
DEFAULT_SYSTEM_PROMPT = os.getenv('DEFAULT_SYSTEM_PROMPT', 'Você é Têmis, um assistente inteligente e útil. Responda de forma clara, precisa e amigável.')
try:
    MAX_TOKENS_PER_RESPONSE = int(os.getenv('MAX_TOKENS_PER_RESPONSE', 500))
    MIN_PROVIDER_LIMIT = min(info['max_tokens_limit'] for info in CONFIG_MODELOS.values())
    if MAX_TOKENS_PER_RESPONSE > MIN_PROVIDER_LIMIT:
        print(f"Aviso: MAX_TOKENS_PER_RESPONSE ajustado para {MIN_PROVIDER_LIMIT}.")
        MAX_TOKENS_PER_RESPONSE = MIN_PROVIDER_LIMIT
    elif MAX_TOKENS_PER_RESPONSE < 1:
        print("Aviso: MAX_TOKENS_PER_RESPONSE ajustado para 1.")
        MAX_TOKENS_PER_RESPONSE = 1
except ValueError:
    MAX_TOKENS_PER_RESPONSE = 500
    print("Erro: MAX_TOKENS_PER_RESPONSE inválido. Usando padrão (500).")

# Inicializa memória e URLs
MEMORIA = ConversationBufferMemory()
JSON_URL = "http://fibermobile.com.br/temisai/listatemis.php"
BASE_URL = 'http://fibermobile.com.br/temisai/'

# Inicializa variáveis globais
app.config['chat_model'] = None
app.config['prompt_template'] = None

# Função para formatar mensagens
def formatar_mensagem(content):
    parts = content.split("```")
    formatted_content = ""
    inside_code_block = False

    # Função auxiliar para detectar se um texto parece ser um script/código
    def is_code_block(text):
        # Palavras-chave comuns que indicam código
        code_keywords = r'^(def|function|class|import|from|if|for|while|try|catch|\s*[\w]+\s*\()'
        lines = text.split('\n')
        # Verifica se há indentação ou palavras-chave de código
        has_indentation = any(line.startswith(('    ', '\t')) for line in lines)
        has_code_keyword = any(re.match(code_keywords, line) for line in lines)
        return has_indentation or has_code_keyword

    for i, part in enumerate(parts):
        if inside_code_block:
            if i < len(parts) - 1:  # Garante que há um fechamento de bloco de código
                code_content = part.strip()
                if '\n' in code_content:
                    lang, code = code_content.split('\n', 1)
                    lang = lang.strip()
                else:
                    lang = ''
                    code = code_content
                code = code.replace('&', '&').replace('<', '<').replace('>', '>')
                formatted_content += f"<pre><code class=\"language-{lang}\">{code}</code></pre>"
        else:
            # Verifica se o texto parece ser um script/código
            if is_code_block(part):
                # Trata como um bloco de código, mesmo sem "```"
                code = part.replace('&', '&').replace('<', '<').replace('>', '>')
                formatted_content += f"<pre><code>{code}</code></pre>"
            else:
                # Processa como texto normal, procurando por HTML ou parágrafos
                html_pattern = r'<!DOCTYPE\s+html>[\s\S]*?</html>|<html[\s\S]*?</html>|<!DOCTYPE\s+html>[\s\S]*|<html[\s\S]*'
                matches = re.finditer(html_pattern, part, re.IGNORECASE)
                last_pos = 0
                for match in matches:
                    start, end = match.span()
                    before_text = part[last_pos:start].strip()
                    if before_text:
                        paragraphs = before_text.split('\n')
                        formatted_content += "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())
                    html_code = match.group(0).replace('&', '&').replace('<', '<').replace('>', '>')
                    formatted_content += f"<pre><code class=\"language-html\">{html_code}</code></pre>"
                    last_pos = end
                remaining_text = part[last_pos:].strip()
                if remaining_text:
                    if is_code_block(remaining_text):
                        code = remaining_text.replace('&', '&').replace('<', '<').replace('>', '>')
                        formatted_content += f"<pre><code>{code}</code></pre>"
                    else:
                        paragraphs = remaining_text.split('\n')
                        formatted_content += "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())
        inside_code_block = not inside_code_block

    # Caso não haja blocos de código e o conteúdo não tenha sido formatado ainda
    if not parts[1:] and formatted_content == "":
        if is_code_block(content):
            content = content.replace('&', '&').replace('<', '<').replace('>', '>')
            formatted_content = f"<pre><code>{content}</code></pre>"
        else:
            html_pattern = r'<!DOCTYPE\s+html>[\s\S]*|<\s*html[\s\S]*'
            if re.match(html_pattern, content.strip(), re.IGNORECASE):
                content = content.replace('&', '&').replace('<', '<').replace('>', '>')
                formatted_content = f"<pre><code class=\"language-html\">{content}</code></pre>"
            else:
                paragraphs = content.split('\n')
                formatted_content = "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())

    return formatted_content

# Funções para carregar documentos
def carrega_arquivos(entrada, is_file=False):
    try:
        if is_file:
            raise ValueError("Processamento de arquivos deve ser feito no cliente.")
        else:
            if not validators.url(entrada):
                raise ValueError("URL inválida.")
            response = requests.get(entrada)
            soup = BeautifulSoup(response.content, 'html.parser')
            documento = soup.get_text()
        return documento
    except Exception as e:
        print(f"Erro ao carregar: {str(e)}")
        return "Erro ao carregar o documento."

def carrega_pdf(caminho):
    try:
        with open(caminho, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            texto = ""
            for page in pdf_reader.pages:
                texto += page.extract_text() + "\n"
        return texto
    except Exception as e:
        print(f"Erro ao carregar PDF: {str(e)}")
        return f"Erro ao carregar PDF: {str(e)}"

def carrega_docx(caminho):
    try:
        doc = Document(caminho)
        texto = ""
        for para in doc.paragraphs:
            texto += para.text + "\n"
        return texto
    except Exception as e:
        print(f"Erro ao carregar DOCX: {str(e)}")
        return f"Erro ao carregar DOCX: {str(e)}"

# Função para inicializar o modelo
def inicializa_modelo(provedor, modelo, api_key, system_prompt=None):
    if not api_key:
        print(f"Erro: Nenhuma API Key fornecida para {provedor}.")
        return None
    data_atual = datetime.now().strftime("%d de %B de %Y")
    system_message = f"{system_prompt if system_prompt else DEFAULT_SYSTEM_PROMPT} Hoje é {data_atual}."
    try:
        template = ChatPromptTemplate.from_messages([
            ('system', system_message),
            ('placeholder', '{chat_history}'),
            ('user', '{input}')
        ])
        max_tokens_limit = CONFIG_MODELOS[provedor]['max_tokens_limit']
        adjusted_max_tokens = min(MAX_TOKENS_PER_RESPONSE, max_tokens_limit)
        if adjusted_max_tokens != MAX_TOKENS_PER_RESPONSE:
            print(f"Aviso: MAX_TOKENS_PER_RESPONSE ajustado para {adjusted_max_tokens}.")
        
        if not app.config['chat_model'] or app.config.get('provedor') != provedor or app.config.get('modelo') != modelo:
            print(f"Tentando inicializar {provedor}/{modelo} com API Key: {api_key[:5]}...")  # Log parcial da chave
            chat = CONFIG_MODELOS[provedor]['chat'](
                model=modelo,
                api_key=api_key,
                max_tokens=adjusted_max_tokens
            )
            app.config['chat_model'] = chat
        chain = template | app.config['chat_model']
        app.config['prompt_template'] = template
        print(f"Modelo {provedor}/{modelo} configurado com max_tokens: {adjusted_max_tokens}")
        return chain
    except Exception as e:
        print(f"Erro ao inicializar {provedor}/{modelo}: {str(e)}")
        return None

# Rota para mudar a especialidade
@app.route('/set-specialty', methods=['POST'])
def set_specialty():
    global MEMORIA
    specialty = request.form.get('specialty')
    if specialty not in PROMPTS_ESPECIALIDADES:
        return jsonify({'success': False, 'message': 'Especialidade inválida.'}), 400

    MEMORIA = ConversationBufferMemory()
    app.config['last_document'] = None
    app.config['last_document_name'] = None

    system_prompt = PROMPTS_ESPECIALIDADES[specialty]
    provedor = app.config.get('provedor', 'DeepSeek')
    modelo = app.config.get('modelo', 'deepseek-chat')
    api_key = app.config.get('api_key') or os.getenv(f'{provedor.upper()}_API_KEY')

    chain = inicializa_modelo(provedor, modelo, api_key, system_prompt)
    if chain:
        app.config['chain'] = chain
        app.config['system_prompt'] = system_prompt
        intro_message = f"Oi! Sou especialista em {specialty}. Como posso ajudá-lo hoje?"
        MEMORIA.chat_memory.add_ai_message(intro_message)
        return jsonify({'success': True, 'message': intro_message})
    else:
        return jsonify({'success': False, 'message': 'Erro ao configurar a especialidade.'}), 500

# Rota principal
@app.route('/', methods=['GET', 'POST'])
def index():
    global MEMORIA
    chain = app.config.get('chain')
    files = app.config.get('files')

    # Se o chain não estiver inicializado, tenta inicializar
    if not chain:
        provedor_padrao = 'DeepSeek'
        modelo_padrao = 'deepseek-chat'
        api_key_padrao = os.getenv('DEEPSEEK_API_KEY')
        if api_key_padrao:
            chain = inicializa_modelo(provedor_padrao, modelo_padrao, api_key_padrao)
            if chain:
                app.config['chain'] = chain
                app.config['provedor'] = provedor_padrao
                app.config['modelo'] = modelo_padrao
                print("Modelo inicializado automaticamente na rota /.")
            else:
                print("Falha ao inicializar o modelo automaticamente na rota /.")

    if request.method == 'POST':
        mensagem = request.form.get('mensagem', '').strip()
        file_content = request.form.get('file_content')
        file_name = request.form.get('file_name')
        bot_message = None

        if mensagem:
            MEMORIA.chat_memory.add_user_message(mensagem)
            if chain:
                if mensagem.startswith("Carregar arquivo:") and file_content and file_name:
                    app.config['last_document'] = file_content
                    app.config['last_document_name'] = file_name
                    bot_message = f"Arquivo '{file_name}' carregado com sucesso!"
                    MEMORIA.chat_memory.add_ai_message(bot_message)
                elif validators.url(mensagem):
                    documento = carrega_arquivos(mensagem, is_file=False)
                    if "Erro" in documento:
                        bot_message = documento
                        MEMORIA.chat_memory.add_ai_message(bot_message)
                    else:
                        app.config['last_document'] = documento
                        app.config['last_document_name'] = mensagem.split('/')[-1]
                        bot_message = f"Documento da URL '{mensagem.split('/')[-1]}' carregado com sucesso!"
                        MEMORIA.chat_memory.add_ai_message(bot_message)
                elif mensagem.lower() in ["listar", "lista"]:
                    resposta = listar_arquivos_por_palavras_chave(files)
                    MEMORIA.chat_memory.add_ai_message(resposta)
                    bot_message = resposta
                else:
                    last_document_name = app.config.get('last_document_name')
                    last_document = app.config.get('last_document')
                    if last_document and ("analise o arquivo" in mensagem.lower() or "analise o documento" in mensagem.lower() or "sobre o arquivo" in mensagem.lower() or "sobre o documento" in mensagem.lower()):
                        try:
                            input_with_document = (
                                f"O seguinte documento foi carregado anteriormente:\n"
                                f"####\n"
                                f"{last_document}\n"
                                f"####\n"
                                f"Com base no documento acima, responda à seguinte pergunta: {mensagem}"
                            )
                            resposta = chain.invoke({
                                'input': input_with_document,
                                'chat_history': MEMORIA.buffer_as_messages
                            }).content.replace('$', 'S')
                            resposta = formatar_mensagem(resposta)
                        except Exception as e:
                            resposta = f"Erro ao analisar o documento '{last_document_name}': {str(e)}"
                    else:
                        nome_arquivo = mensagem.strip().lower().replace('\u200b', '').replace('** | **', '')
                        arquivo_existe = any(f['name'].lower().replace('\u200b', '') == nome_arquivo for f in files)
                        if arquivo_existe:
                            resultado = carregar_arquivo_por_nome(mensagem.replace('**', ''), files)
                            resposta = resultado if resultado else "Erro ao carregar o arquivo."
                        else:
                            try:
                                if last_document:
                                    input_with_document = (
                                        f"O seguinte documento foi carregado anteriormente:\n"
                                        f"####\n"
                                        f"{last_document}\n"
                                        f"####\n"
                                        f"Com base no documento acima (se relevante), responda à seguinte pergunta: {mensagem}"
                                    )
                                    resposta = chain.invoke({
                                        'input': input_with_document,
                                        'chat_history': MEMORIA.buffer_as_messages
                                    }).content.replace('$', 'S')
                                else:
                                    resposta = chain.invoke({
                                        'input': mensagem,
                                        'chat_history': MEMORIA.buffer_as_messages
                                    }).content.replace('$', 'S')
                                resposta = formatar_mensagem(resposta)
                            except Exception as e:
                                resposta = f"Erro ao processar a mensagem: {str(e)}"
                    MEMORIA.chat_memory.add_ai_message(resposta)
                    bot_message = resposta
            else:
                bot_message = "Modelo não inicializado. Configure na página de configurações."

        if bot_message is None:
            bot_message = "Nenhuma ação realizada."
        return jsonify({'bot_message': bot_message})

    if not MEMORIA.buffer_as_messages:
        system_prompt = app.config.get('system_prompt', '')
        if system_prompt:
            intro_message = f"Olá! {system_prompt} Como posso ajudar você hoje?"
        else:
            intro_message = f"Olá! Eu sou Têmis, um assistente inteligente e útil. Como posso ajudar você hoje?"
        MEMORIA.chat_memory.add_ai_message(intro_message)
    return render_template('index.html', messages=MEMORIA.buffer_as_messages)

# Rota para limpar a memória
@app.route('/clear-memory', methods=['POST'])
def clear_memory():
    global MEMORIA
    try:
        MEMORIA = ConversationBufferMemory()
        app.config['last_document'] = None
        app.config['last_document_name'] = None
        app.config['system_prompt'] = DEFAULT_SYSTEM_PROMPT  # Redefine para o prompt padrão do config.env
        # Reinicializa o modelo com o prompt padrão
        provedor = app.config.get('provedor', 'DeepSeek')
        modelo = app.config.get('modelo', 'deepseek-chat')
        api_key = app.config.get('api_key') or os.getenv(f'{provedor.upper()}_API_KEY')
        chain = inicializa_modelo(provedor, modelo, api_key, DEFAULT_SYSTEM_PROMPT)
        if chain:
            app.config['chain'] = chain
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Rota para verificar a senha de configuração
@app.route('/check-config-password', methods=['POST'])
def check_config_password():
    password = request.form.get('password', '')
    if password == CONFIG_PASSWORD:
        session['config_access'] = True
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Senha incorreta.'})

# Rota para a página de configurações
@app.route('/config', methods=['GET', 'POST'])
def config():
    if not session.get('config_access'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        provedor = request.form.get('provedor')
        modelo = request.form.get('modelo')
        api_key = request.form.get('api_key') or os.getenv(f'{provedor.upper()}_API_KEY')
        system_prompt = request.form.get('system_prompt', '').strip()

        if (provedor != app.config.get('provedor') or 
            modelo != app.config.get('modelo') or 
            (request.form.get('api_key') and request.form.get('api_key') != app.config.get('api_key'))):
            chain = inicializa_modelo(provedor, modelo, api_key, system_prompt)
        else:
            data_atual = datetime.now().strftime("%d de %B de %Y")
            system_message = f"{system_prompt if system_prompt else DEFAULT_SYSTEM_PROMPT} Hoje é {data_atual}."
            app.config['prompt_template'] = ChatPromptTemplate.from_messages([
                ('system', system_message),
                ('placeholder', '{chat_history}'),
                ('user', '{input}')
            ])
            chain = app.config['prompt_template'] | app.config['chat_model']

        if chain:
            app.config['chain'] = chain
            app.config['provedor'] = provedor
            app.config['modelo'] = modelo
            app.config['api_key'] = api_key if request.form.get('api_key') else None
            app.config['system_prompt'] = system_prompt
            flash("Configuração salva com sucesso!")
            return redirect(url_for('index'))
        else:
            flash("Erro ao inicializar o modelo.")

    return render_template(
        'config.html',
        config_modelos=CONFIG_MODELOS,
        current_provedor=app.config.get('provedor', 'DeepSeek'),
        current_modelo=app.config.get('modelo', 'deepseek-chat'),
        current_api_key=app.config.get('api_key', ''),
        current_system_prompt=app.config.get('system_prompt', '')
    )

# Rota para baixar o histórico
@app.route('/download')
def download():
    historico = "\n".join([f"{msg.type}: {msg.content}" for msg in MEMORIA.buffer_as_messages])
    return send_file(
        io.BytesIO(historico.encode('utf-8')),
        as_attachment=True,
        download_name="historico_conversa.txt"
    )

# Funções auxiliares
def list_json_files():
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(JSON_URL, headers=headers, timeout=10)
        data = response.json()
        files = [{'name': f, 'url': f"{BASE_URL}{f}"} for f in data.get('arquivos', []) if not f.lower().endswith('.php')]
        return files if files else []
    except Exception as e:
        print(f"Erro ao acessar {JSON_URL}: {str(e)}")
        return []

def listar_arquivos_por_palavras_chave(files):
    if not files:
        return "Não foi possível listar os arquivos."
    resposta = "Lista de Arquivos:<br><br>"
    arquivos_listados = [f"{f['name']}" for f in files]
    return resposta + "<br>".join(arquivos_listados)

def carregar_arquivo_por_nome(nome_arquivo, files):
    chain = app.config.get('chain')
    nome_arquivo = nome_arquivo.strip().lower().replace('\u200b', '').replace('**', '')
    arquivo = next((f for f in files if f['name'].lower().replace('\u200b', '') == nome_arquivo), None)
    if arquivo:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(arquivo['url'], headers=headers, timeout=10)
            response.raise_for_status()
            extensao = arquivo['name'].split('.')[-1].lower()
            with tempfile.NamedTemporaryFile(suffix=f'.{extensao}', delete=False) as temp:
                temp.write(response.content)
                if extensao == 'pdf':
                    documento = carrega_pdf(temp.name)
                elif extensao == 'docx':
                    documento = carrega_docx(temp.name)
                elif extensao in ['txt', 'text']:
                    documento = open(temp.name, 'r', encoding='utf-8').read()
                elif extensao in ['xls', 'xlsx']:
                    df = pd.read_excel(temp.name)
                    documento = df.to_string(index=False)
                elif extensao == 'csv':
                    df = pd.read_csv(temp.name)
                    documento = df.to_string(index=False)
                else:
                    os.unlink(temp.name)
                    return f"Erro: Tipo de arquivo '{extensao}' não suportado."
            os.unlink(temp.name)
            app.config['last_document'] = documento
            app.config['last_document_name'] = arquivo['name']
            return f"Documento '{arquivo['name']}' carregado com sucesso!"
        except requests.exceptions.RequestException as e:
            return f"Erro: Não foi possível baixar o arquivo '{arquivo['name']}'."
    return None

# Rota para verificar o e-mail usando a API fornecida
@app.route('/check-email', methods=['POST'])
def check_email():
    email = request.form.get('email', '').strip()
    if not email:
        return jsonify({'success': False, 'message': 'E-mail não fornecido.'}), 400

    api_url = os.getenv('API_USE')
    if not api_url:
        return jsonify({'success': False, 'message': 'Erro: URL da API não configurada.'}), 500

    try:
        response = requests.get(api_url, timeout=10)
        print(f"Status da resposta: {response.status_code}")
        print(f"Resposta bruta da API: {response.text}")
        response.raise_for_status()
        data = response.json()

        if not (data and isinstance(data, dict)):
            return jsonify({'success': False, 'message': 'Dados da API inválidos ou vazios.'}), 400

        email_sem_pontos = email.replace('.', '').lower()
        email_key = next((key for key in data.keys() if key.lower() == email_sem_pontos), None)
        if not email_key:
            return jsonify({'success': False, 'message': f'O e-mail {email} não foi encontrado.'})

        email_data = data[email_key]
        if not isinstance(email_data, dict):
            return jsonify({'success': False, 'message': f'O e-mail {email} foi encontrado, mas os dados não são um dicionário: {type(email_data)}.'})

        email_chave_dict = email.replace('.', '')
        if email_chave_dict not in email_data:
            return jsonify({'success': False, 'message': f'O e-mail {email} foi encontrado, mas o dicionário não contém a chave "{email_chave_dict}": {email_data.keys()}.'})

        value = email_data[email_chave_dict]
        print(f"Valor de 'value' antes do json.loads: {value}")
        if not isinstance(value, str):
            return jsonify({'success': False, 'message': f'O valor da chave "{email_chave_dict}" não é uma string JSON: tipo {type(value)}.'})

        try:
            sublist = json.loads(value)
            if not isinstance(sublist, list):
                return jsonify({'success': False, 'message': f'O valor desserializado da chave "{email_chave_dict}" não é uma lista: tipo {type(sublist)}.'})
        except json.JSONDecodeError as e:
            return jsonify({'success': False, 'message': f'Erro ao desserializar o valor da chave "{email_chave_dict}": {str(e)}.'})

        if len(sublist) <= 6:
            return jsonify({'success': False, 'message': f'A sublista para o e-mail {email} tem menos de 7 elementos: {len(sublist)} elementos.'})

        item_7 = sublist[6]
        return jsonify({'success': True, 'message': f'O item 7 para o e-mail {email} é: "{item_7}".', 'item_7': item_7})

    except requests.exceptions.RequestException as e:
        print(f"Erro ao acessar a API: {str(e)}")
        return jsonify({'success': False, 'message': f'Erro ao verificar o e-mail {email}: problema ao acessar a API.'}), 500

# Função para inicializar o modelo padrão
def inicializa_modelo_padrao():
    provedor_padrao = 'DeepSeek'
    modelo_padrao = 'deepseek-chat'
    api_key_padrao = os.getenv('DEEPSEEK_API_KEY')
    print(f"DEEPSEEK_API_KEY carregada: {api_key_padrao}")  # Log da chave
    if api_key_padrao:
        chain = inicializa_modelo(provedor_padrao, modelo_padrao, api_key_padrao)
        if chain:
            app.config['chain'] = chain
            app.config['provedor'] = provedor_padrao
            app.config['modelo'] = modelo_padrao
            app.config['api_key'] = None
            app.config['system_prompt'] = None
            print(f"Modelo padrão {provedor_padrao}/{modelo_padrao} inicializado.")
        else:
            print("Falha ao inicializar o modelo padrão.")
    else:
        print("Nenhuma API Key padrão encontrada.")

# Inicializa a aplicação
if __name__ == '__main__':
    app.config['files'] = list_json_files()
    inicializa_modelo_padrao()
    app.run(debug=True, host='0.0.0.0', port=5000)