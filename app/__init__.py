from flask import Flask
from .extensions import cors, db, jwt, migrate
from .errors import register_error_handlers


def create_app(config_object="config.Config"):
    app = Flask(__name__)
    app.config.from_object(config_object)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    origins = [origin.strip() for origin in app.config["FRONTEND_ORIGIN"].split(",") if origin.strip()]
    cors.init_app(app, resources={r"/api/*": {"origins": origins}}, supports_credentials=False)
    register_error_handlers(app)

    @jwt.unauthorized_loader
    def missing_token(reason):
        return {"error": "autenticacion_requerida", "detail": reason}, 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return {"error": "token_invalido", "detail": reason}, 401

    @jwt.expired_token_loader
    def expired_token(_header, _payload):
        return {"error": "token_expirado", "detail": "La sesión expiró. Inicie sesión nuevamente."}, 401

    from .blueprints.auth import bp as auth_bp
    from .blueprints.planes import bp as planes_bp
    from .blueprints.cursos import bp as cursos_bp
    from .blueprints.alumnos import bp as alumnos_bp
    from .blueprints.periodos import bp as periodos_bp
    from .blueprints.secciones import bp as secciones_bp
    from .blueprints.matriculas import bp as matriculas_bp
    for blueprint in (auth_bp, planes_bp, cursos_bp, alumnos_bp, periodos_bp, secciones_bp, matriculas_bp):
        app.register_blueprint(blueprint, url_prefix="/api")

    @app.get("/health")
    def health():
        return {"status": "ok"}
    return app
