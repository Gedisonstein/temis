from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response
from app import app  # importa o Flask app normal

application = DispatcherMiddleware(
    Response('Not Found', status=404),
    {
        '/temis': app
    }
)
