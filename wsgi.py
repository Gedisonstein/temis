from app import app
from werkzeug.middleware.dispatcher import DispatcherMiddleware

application = DispatcherMiddleware(None, {
    '/temis': app
})

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple('0.0.0.0', 8000, application)
