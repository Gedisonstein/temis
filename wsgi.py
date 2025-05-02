from werkzeug.middleware.dispatcher import DispatcherMiddleware
from temis import application  # ou o nome do seu arquivo principal sem .py

application = DispatcherMiddleware(None, {
    '/temis': application
})
