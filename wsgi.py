from werkzeug.middleware.dispatcher import DispatcherMiddleware
from temis import app  # ou o nome do seu arquivo principal sem .py

application = DispatcherMiddleware(None, {
    '/temis': app
})
