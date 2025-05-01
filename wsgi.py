from app import app  # Importa o application em vez do app

if __name__ == "__main__":
    # Use o werkzeug run_simple para executar a aplicação middleware
    from werkzeug.serving import run_simple
    run_simple('localhost', 5000, application, use_reloader=True)
