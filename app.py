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
import logging
from werkzeug.middleware.dispatcher import DispatcherMiddleware

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Inicializa o Flask
app = Flask(__name__, static_url_path='/temis/static', static_folder='static')  # Isso é CRUCIAL para os assets
app.config['APPLICATION_ROOT'] = '/temis'
app.secret_key = 'sua_chave_secreta_aqui'  # Altere para uma chave segura

# Limite de tamanho das requisições (50 MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

# Configura logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carrega variáveis de ambiente
load_dotenv("config.env")
os.environ['USER_AGENT'] = 'AssistenteApp/1.0'

# Carrega a senha de configuração
CONFIG_PASSWORD = os.getenv('CONFIG_PASSWORD', '')  # Senha padrão

# Carrega e valida a API_USE
API_USE = os.getenv('API_USE')
if not validators.url(API_USE):
    print(f"Erro: API_USE ({API_USE}) não é uma URL válida. Verifique o config.env.")
    API_USE = "none"

# Configuração dos modelos com limites de max_tokens por provedor
CONFIG_MODELOS = {
    'DeepSeek': {
        'modelos': ['deepseek-coder', 'deepseek-chat'],
        'chat': ChatDeepSeek,
        'max_tokens_limit': 8192
    },
    'OpenAI': {
        'modelos': ['gpt-3.5-turbo', 'gpt-4'],
        'chat': ChatOpenAI,
        'max_tokens_limit': 4096
    },
    'Groq': {
        'modelos': ['llama3-8b-8192', 'llama3-70b-8192', 'mixtral-8x7b-32768'],
        'chat': ChatGroq,
        'max_tokens_limit': 32768
    }
}

# Dicionário de prompts por especialidade
PROMPTS_ESPECIALIDADES = {
    "Direito Administrativo": """Você é um assistente virtual especializado em Direito Administrativo, com amplo conhecimento em legislação, jurisprudência, doutrina e práticas relacionadas ao direito público no Brasil. Sua função é fornecer informações precisas, claras e atualizadas sobre temas como licitações, contratos administrativos, servidores públicos, improbidade administrativa, processos administrativos, controle da administração pública, entre outros. Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos. Além disso, esteja preparado para: analisar casos concretos e sugerir possíveis soluções com base na legislação vigente; esclarecer dúvidas sobre legislação, prazos, procedimentos e recursos; fornecer modelos de petições, recursos ou documentos, quando solicitado. Sua linguagem deve ser formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada a tema jurídico, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte.""",
    "Direito Penal": """Você é um assistente virtual especializado em Direito Penal, com domínio da legislação penal brasileira, jurisprudência, doutrina e princípios do direito criminal. Responda com precisão sobre crimes, penas, processos penais, medidas cautelares, execução penal e garantias constitucionais, citando sempre o Código Penal, a Constituição e decisões relevantes do STF e STJ. Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos. Além disso, esteja preparado para: analisar casos concretos e sugerir possíveis soluções com base na legislação vigente; esclarecer dúvidas sobre legislação, prazos, procedimentos e recursos; fornecer modelos de petições, recursos ou documentos, quando solicitado. Sua linguagem deve ser formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada a tema jurídico, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte.""",
    "Processo Penal": """Você é um assistente virtual especializado em Processo Penal, com expertise no Código de Processo Penal brasileiro. Forneça informações detalhadas sobre fases do processo, recursos, prazos, provas, audiências e direitos processuais, baseando-se em leis e jurisprudências do STF e STJ. Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos. Além disso, esteja preparado para: analisar casos concretos e sugerir possíveis soluções com base na legislação vigente; esclarecer dúvidas sobre legislação, prazos, procedimentos e recursos; fornecer modelos de petições, recursos ou documentos, quando solicitado. Sua linguagem deve ser formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada a tema jurídico, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte.""",
    "Direito Cívil": """Você é um assistente virtual especializado em Direito Civil, com conhecimento profundo do Código Civil brasileiro, contratos, responsabilidade civil, direitos reais, família e sucessões. Responda com base legal e jurisprudencial, adaptando-se ao público. Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos. Além disso, esteja preparado para: analisar casos concretos e sugerir possíveis soluções com base na legislação vigente; esclarecer dúvidas sobre legislação, prazos, procedimentos e recursos; fornecer modelos de petições, recursos ou documentos, quando solicitado. Sua linguagem deve ser formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada a tema jurídico, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte.""",
    "Processo Cívil": """Você é um assistente virtual especializado em Processo Civil, com domínio do Código de Processo Civil brasileiro. Oriente sobre procedimentos, prazos, recursos, petições e execução, citando leis e jurisprudências relevantes. Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos. Além disso, esteja preparado para: analisar casos concretos e sugerir possíveis soluções com base na legislação vigente; esclarecer dúvidas sobre legislação, prazos, procedimentos e recursos; fornecer modelos de petições, recursos ou documentos, quando solicitado. Sua linguagem deve be formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada a tema jurídico, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte.""",
    "Direito Consumidor": """Você é um assistente virtual especializado em Direito do Consumidor, com base no Código de Defesa do Consumidor (CDC). Responda sobre relações de consumo, direitos do consumidor, contratos, práticas abusivas e ações judiciais, citando o CDC e jurisprudências. Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos. Além disso, esteja preparado para: analisar casos concretos e sugerir possíveis soluções com base na legislação vigente; esclarecer dúvidas sobre legislação, prazos, procedimentos e recursos; fornecer modelos de petições, recursos ou documentos, quando solicitado. Sua linguagem deve ser formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada a tema jurídico, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte.""",
    "Direito Tributário": """Você é um assistente virtual especializado em Direito Tributário, com conhecimento em tributos, impostos, taxas, contribuições e processos fiscais no Brasil. Baseie-se no Código Tributário Nacional, leis específicas e decisões do STF e STJ. Ao responder, sempre cite a base legal (leis, decretos, súmulas, etc.) e, quando possível, referencie jurisprudências relevantes do STF (Supremo Tribunal Federal) e do STJ (Superior Tribunal de Justiça). Se necessário, explique conceitos de forma didática para facilitar a compreensão de leigos. Além disso, esteja preparado para: analisar casos concretos e sugerir possíveis soluções com base na legislação vigente; esclarecer dúvidas sobre legislação, prazos, procedimentos e recursos; fornecer modelos de petições, recursos ou documentos, quando solicitado. Sua linguagem deve ser formal, técnica e precisa, mas adaptável ao nível de conhecimento do usuário. Caso a pergunta não esteja relacionada a tema jurídico, informe que sua especialidade é nessa área e sugira buscar orientação em outra fonte."""
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

# Inicializa variáveis globais
app.config['chat_model'] = None
app.config['prompt_template'] = None
app.config['model_initialized'] = False  # Flag para rastrear inicialização

# Verifica arquivos estáticos
STATIC_FILES = ['logo.png', 'logo_2.png', 'QR.png', 'novo_chat.png']
for static_file in STATIC_FILES:
    if not os.path.exists(os.path.join(app.static_folder or 'static', static_file)):
        print(f"Aviso: Arquivo estático '{static_file}' não encontrado no diretório 'static'.")

# Função para formatar mensagens
def formatar_mensagem(content):
    parts = content.split("```")
    formatted_content = ""
    inside_code_block = False

    def is_code_block(text):
        code_keywords = r'^(def|function|class|import|from|if|for|while|try|catch|\s*[\w]+\s*\()'
        lines = text.split('\n')
        has_indentation = any(line.startswith(('    ', '\t')) for line in lines)
        has_code_keyword = any(re.match(code_keywords, line) for line in lines)
        return has_indentation or has_code_keyword

    for i, part in enumerate(parts):
        if inside_code_block:
            if i < len(parts) - 1:
                code_content = part.strip()
                if '\n' in code_content:
                    lang, code = code_content.split('\n', 1)
                    lang = lang.strip()
                else:
                    lang = ''
                    code = code_content
                code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                formatted_content += f"<pre><code class=\"language-{lang}\">{code}</code></pre>"
        else:
            if is_code_block(part):
                code = part.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                formatted_content += f"<pre><code>{code}</code></pre>"
            else:
                html_pattern = r'<!DOCTYPE\s+html>[\s\S]*?</html>|<html[\s\S]*?</html>|<!DOCTYPE\s+html>[\s\S]*|<html[\s\S]*'
                matches = re.finditer(html_pattern, part, re.IGNORECASE)
                last_pos = 0
                for match in matches:
                    start, end = match.span()
                    before_text = part[last_pos:start].strip()
                    if before_text:
                        paragraphs = before_text.split('\n')
                        formatted_content += "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())
                    html_code = match.group(0).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    formatted_content += f"<pre><code class=\"language-html\">{html_code}</code></pre>"
                    last_pos = end
                remaining_text = part[last_pos:].strip()
                if remaining_text:
                    if is_code_block(remaining_text):
                        code = remaining_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        formatted_content += f"<pre><code>{code}</code></pre>"
                    else:
                        paragraphs = remaining_text.split('\n')
                        formatted_content += "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())
        inside_code_block = not inside_code_block

    if not parts[1:] and formatted_content == "":
        if is_code_block(content):
            content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            formatted_content = f"<pre><code>{content}</code></pre>"
        else:
            html_pattern = r'<!DOCTYPE\s+html>[\s\S]*|<\s*html[\s\S]*'
            if re.match(html_pattern, content.strip(), re.IGNORECASE):
                content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
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
            response.raise_for_status()  # Levanta exceção para erros HTTP
            soup = BeautifulSoup(response.content, 'html.parser')
            documento = soup.get_text()
        return documento
    except requests.exceptions.RequestException as e:
        print(f"Erro ao carregar URL {entrada}: {str(e)}")
        return f"Erro ao carregar o documento da URL: {str(e)}"
    except Exception as e:
        print(f"Erro inesperado ao carregar: {str(e)}")
        return f"Erro ao carregar o documento: {str(e)}"

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

# Função para inicializar os modelos
def inicializa_modelo(provedor, modelo, api_key, system_prompt=None):
    logger.info(f"Tentando inicializar {provedor}/{modelo}")
    if not api_key:
        logger.error(f"Erro: Nenhuma API Key fornecida para {provedor}")
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
        chat = CONFIG_MODELOS[provedor]['chat'](
            model=modelo,
            api_key=api_key,
            max_tokens=adjusted_max_tokens
        )
        app.config['chat_model'] = chat
        chain = template | chat
        app.config['prompt_template'] = template
        logger.info(f"Modelo {provedor}/{modelo} configurado com max_tokens: {adjusted_max_tokens}")
        return chain
    except Exception as e:
        logger.error(f"Erro ao inicializar {provedor}/{modelo}: {str(e)}")
        return None

def inicializa_modelo_padrao():
    provedor_padrao = 'DeepSeek'
    modelo_padrao = 'deepseek-chat'
    api_key_padrao = os.getenv('DEEPSEEK_API_KEY')
    logger.info("Inicializando modelo padrão")
    if api_key_padrao:
        chain = inicializa_modelo(provedor_padrao, modelo_padrao, api_key_padrao)
        if chain:
            app.config['chain'] = chain
            app.config['provedor'] = provedor_padrao
            app.config['modelo'] = modelo_padrao
            app.config['api_key'] = None
            app.config['system_prompt'] = None
            app.config['model_initialized'] = True
            logger.info("Modelo inicializado com sucesso")
        else:
            app.config['model_initialized'] = False
            logger.error("Falha ao inicializar o modelo")
    else:
        app.config['model_initialized'] = False
        logger.error("Nenhuma API Key encontrada")

# Rota para mudar a especialidade
@app.route('/set-specialty', methods=['POST'])
def set_specialty():
    specialty = request.form.get('specialty')
    if specialty not in PROMPTS_ESPECIALIDADES:
        return jsonify({'success': False, 'message': 'Especialidade inválida.'}), 400

    # Reseta a sessão do usuário
    session['chat_memory'] = []
    session['last_document'] = None
    session['last_document_name'] = None

    system_prompt = PROMPTS_ESPECIALIDADES[specialty]
    provedor = app.config.get('provedor', 'DeepSeek')
    modelo = app.config.get('modelo', 'deepseek-chat')
    api_key = app.config.get('api_key') or os.getenv(f'{provedor.upper()}_API_KEY')

    chain = inicializa_modelo(provedor, modelo, api_key, system_prompt)
    if chain:
        app.config['chain'] = chain
        app.config['system_prompt'] = system_prompt
        intro_message = f"Oi! Sou especialista em {specialty}. Como posso ajudá-lo hoje?"
        session['chat_memory'].append({'type': 'ai', 'content': intro_message})
        session.modified = True
        return jsonify({'success': True, 'message': intro_message})
    else:
        return jsonify({'success': False, 'message': 'Erro ao configurar a especialidade.'}), 500

# Rota principal
@app.route('/', methods=['GET', 'POST'])
def index():
    # Inicializa a memória da sessão se não existir
    if 'chat_memory' not in session:
        session['chat_memory'] = []
        session['last_document'] = None
        session['last_document_name'] = None
        chain = app.config.get('chain')
        if chain:
            system_prompt = app.config.get('system_prompt', '')
            if system_prompt:
                intro_message = f"Olá! {system_prompt} Como posso ajudar você hoje?"
            else:
                intro_message = f"Olá! Eu sou Têmis, um assistente inteligente e útil. Como posso ajudar você hoje?"
            session['chat_memory'].append({'type': 'ai', 'content': intro_message})
        session.modified = True

    chain = app.config.get('chain')

    if request.method == 'POST':
        mensagem = request.form.get('mensagem', '').strip()
        file_content = request.form.get('file_content')
        file_name = request.form.get('file_name')
        bot_message = None

        if mensagem:
            session['chat_memory'].append({'type': 'human', 'content': mensagem})
            if chain:
                if mensagem.startswith("Carregar arquivo:") and file_content and file_name:
                    session['last_document'] = file_content
                    session['last_document_name'] = file_name
                    bot_message = f"Arquivo '{file_name}' carregado com sucesso!"
                    session['chat_memory'].append({'type': 'ai', 'content': bot_message})
                elif validators.url(mensagem):
                    documento = carrega_arquivos(mensagem, is_file=False)
                    if "Erro" in documento:
                        bot_message = documento
                        session['chat_memory'].append({'type': 'ai', 'content': bot_message})
                    else:
                        session['last_document'] = documento
                        session['last_document_name'] = mensagem.split('/')[-1]
                        bot_message = f"Documento da URL '{mensagem.split('/')[-1]}' carregado com sucesso!"
                        session['chat_memory'].append({'type': 'ai', 'content': bot_message})
                elif mensagem.lower() in ["listar", "lista"]:
                    bot_message = "Funcionalidade de listar arquivos não está disponível."
                    session['chat_memory'].append({'type': 'ai', 'content': bot_message})
                else:
                    last_document_name = session.get('last_document_name')
                    last_document = session.get('last_document')
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
                                'chat_history': [msg for msg in session['chat_memory']]
                            }).content.replace('$', 'S')
                            resposta = formatar_mensagem(resposta)
                        except Exception as e:
                            resposta = f"Erro ao analisar o documento '{last_document_name}': {str(e)}"
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
                                    'chat_history': [msg for msg in session['chat_memory']]
                                }).content.replace('$', 'S')
                            else:
                                resposta = chain.invoke({
                                    'input': mensagem,
                                    'chat_history': [msg for msg in session['chat_memory']]
                                }).content.replace('$', 'S')
                            resposta = formatar_mensagem(resposta)
                        except Exception as e:
                            resposta = f"Erro ao processar a mensagem: {str(e)}"
                    session['chat_memory'].append({'type': 'ai', 'content': resposta})
                    bot_message = resposta
            else:
                bot_message = "Modelo não inicializado. Configure na página de configurações."
            session.modified = True

        if bot_message is None:
            bot_message = "Nenhuma ação realizada."
        return jsonify({'bot_message': bot_message})

    return render_template('index.html', messages=session['chat_memory'])

# Rota para limpar a memória
@app.route('/clear-memory', methods=['POST'])
def clear_memory():
    try:
        session['chat_memory'] = []
        session['last_document'] = None
        session['last_document_name'] = None
        app.config['system_prompt'] = DEFAULT_SYSTEM_PROMPT
        provedor = app.config.get('provedor', 'DeepSeek')
        modelo = app.config.get('modelo', 'deepseek-chat')
        api_key = app.config.get('api_key') or os.getenv(f'{provedor.upper()}_API_KEY')
        chain = inicializa_modelo(provedor, modelo, api_key, DEFAULT_SYSTEM_PROMPT)
        if chain:
            app.config['chain'] = chain
            intro_message = f"Olá! {DEFAULT_SYSTEM_PROMPT} Como posso ajudar você hoje?"
            session['chat_memory'].append({'type': 'ai', 'content': intro_message})
        session.modified = True
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
    historico = "\n".join([f"{msg['type']}: {msg['content']}" for msg in session.get('chat_memory', [])])
    return send_file(
        io.BytesIO(historico.encode('utf-8')),
        as_attachment=True,
        download_name="historico_conversa.txt"
    )

# Rota para verificar o e-mail usando a API fornecida
@app.route('/check-email', methods=['POST'])
def check_email():
    email = request.form.get('email', '').strip()
    if not email or not API_USE:
        return jsonify({'success': False, 'message': 'E-mail ou API não configurado.'}), 400

    try:
        response = requests.get(API_USE, timeout=10)
        data = response.json()

        email_key = email.replace('.', '').lower()
        if email_key not in data or not isinstance(data[email_key], dict):
            return jsonify({'success': False, 'message': f'E-mail {email} não encontrado ou dados inválidos.'}), 400

        email_data = data[email_key]
        value = email_data.get(email_key)
        if not isinstance(value, str):
            return jsonify({'success': False, 'message': 'Dados do e-mail inválidos.'}), 400

        sublist = json.loads(value)
        if not isinstance(sublist, list) or len(sublist) < 7:
            return jsonify({'success': False, 'message': 'Lista inválida ou insuficiente.'}), 400

        item_7 = sublist[6]
        if item_7 != 'IA':
            return jsonify({'success': False, 'message': f'Usuário {email} não autorizado: Acesse o app e confira seu plano.'}), 400

        return jsonify({'success': True, 'message': f'Usuário {email} autorizado.', 'item_7': item_7}) # esse é o resultado que mostra o email não o index.html

    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        return jsonify({'success': False, 'message': f'Erro ao verificar {email}.'}), 500
    
# Rota para verificar o status de inicialização do modelo
@app.route('/check-model-status', methods=['GET'])
def check_model_status():
    return jsonify({'initialized': app.config['model_initialized']})

# Inicializa a aplicação
inicializa_modelo_padrao()  # Chama a inicialização sempre que o app é carregado

#if __name__ == '__main__':
    #app.run(debug=True, host='0.0.0.0', port=5000)
