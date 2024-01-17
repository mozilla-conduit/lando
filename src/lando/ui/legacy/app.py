# TODO: all the below need to be moved to URLs
app.register_blueprint(pages)
app.register_blueprint(revisions)
app.register_blueprint(dockerflow)
app.register_blueprint(template_helpers)
errorhandlers.register_error_handlers(app)
# TODO: assets_src/assets.yml replacement
