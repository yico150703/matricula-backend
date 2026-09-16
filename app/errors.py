from flask import jsonify


class ApiError(Exception):
    def __init__(self, error, detail=None, status=400):
        self.error = error
        self.detail = detail or error
        self.status = status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error=error.error, detail=error.detail), error.status

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="recurso_no_encontrado", detail="La ruta o recurso solicitado no existe."), 404

    @app.errorhandler(405)
    def method_not_allowed(_):
        return jsonify(error="metodo_no_permitido", detail="El método HTTP no está permitido para este recurso."), 405

    @app.errorhandler(422)
    def invalid_token(_):
        return jsonify(error="token_invalido", detail="El token de autenticación no es válido."), 401
