import datetime
import os
from datetime import datetime
from flask import Flask, render_template, current_app, make_response, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_security import current_user, login_required, RoleMixin, Security, \
    SQLAlchemyUserDatastore, UserMixin, utils
from flask_uploads import configure_uploads
from flaskext.markdown import Markdown
from flask_assets import Bundle
from flask_restful import Api

from .extensions import db, uploaded_images, security, mail, migrate, admin, \
    ckeditor, moment, assets, jwt
from .models import User, Role, Post, Tag, Buzz, RevokedTokenModel
from .models.main import UserAdmin, RoleAdmin # not db tables
from .main.forms import ExtendedRegisterForm
from .api import add_resources


def crash_page(e):
    if 'api' in request.url_root:
        return make_response(jsonify("500 Server error"), 500)
    return render_template('main/500.html'), 500

def page_not_found(e):
    return render_template('main/404.html'), 404

def page_forbidden(e):
    if 'api' in request.url_root: # I wish this worked
        return make_response(jsonify("403 Forbidden"), 403)
    return render_template('main/403.html'), 403


# OUR COOL application factory
def create_app(config_name):
    """ Application factory """
    # Flask init
    app = Flask(__name__) # most of the work done right here. Thanks, Flask!
    app.config.from_object('settings') # load my settings which pull from .env
    
    ''' 
    FLASK EXTENTIONS
    '''
    # load my image uploader extension 
    configure_uploads(app, uploaded_images)
    
    db.init_app(app) # load my database extension
    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    # load my security extension
    security.init_app(app, user_datastore, confirm_register_form=ExtendedRegisterForm)
    mail.init_app(app) # load my mail extensioin 
    # load my writing tool extension 
    md = Markdown(app, extensions=['fenced_code', 'tables'])
    migrate.init_app(app, db) # load my database updater tool
    moment.init_app(app) # time formatting
    
    @jwt.token_in_blacklist_loader
    def check_if_token_in_blacklist(decrypted_token):
        jti = decrypted_token['jti']
        return models.RevokedTokenModel.is_jti_blacklisted(jti)
    jwt.init_app(app) # bolt on our Javascript Web Token tool
    
    ####
    # ASSETS
    ###
    assets.init_app(app)
    js = Bundle('vendor/bootstrap/js/bootstrap.bundle.min.js', 'vendor/jquery-easing/jquery.easing.min.js', 
            'js/sb-admin-2.min.js', 
            filters='jsmin', output='js/packed.js')
    sass = Bundle('scss/custom.scss', filters='scss', output='css/custom.css')
    all_css = Bundle(sass,  # add more CSS files here
                    filters='cssmin', output="css/packed.css")           


    # EXTENSIONS THAT SOMETIMES CRASH
    # TODO: don't be lazy, Mr. A, get rid of this try-except
    try:
        assets.register('js_all', js)
        assets.register('all_css', all_css)
        admin.init_app(app)
        ckeditor.init_app(app)
        admin.add_view(UserAdmin(User, db.session))
        admin.add_view(RoleAdmin(Role, db.session))
        admin.add_view(RoleAdmin(Post, db.session))
        admin.add_view(RoleAdmin(Buzz, db.session))
        # TODO: Add new models here so you can manage data from Flask-Admin's convenient tools
    except Exception as e:
        app.logger.error(f'Failed activating extensions: {e}')

    # TODO: Setup sentry.io!
    # sentry_sdk.init(dsn="", integrations=[FlaskIntegration()])
    
    # activate the flaskinni blueprint (blog, user settings, and other basic routes)
    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    # activate API blueprint: https://stackoverflow.com/questions/38448618/using-flask-restful-as-a-blueprint-in-large-application
    from .api import api_blueprint   
    restful = Api(api_blueprint, prefix="/api/v1") 
    add_resources(restful)
    app.register_blueprint(api_blueprint) # registering the blueprint effectively runs init_app on the restful extension
    
    # --- NEW BLUEPRINTS GO BELOW THIS LINE ---


    # custom error handlers, these call the functions at the top of the file
    app.register_error_handler(500, crash_page)
    app.register_error_handler(404, page_not_found)
    app.register_error_handler(403, page_forbidden)


    # Executes before the first request is processed.
    @app.before_first_request
    def before_first_request():
        """ What do we do before we respond to the first request """

        # Create any database tables that don't exist yet.
        db.create_all()

        # Create the Roles "admin" and "end-user" -- unless they already exist
        user_datastore.find_or_create_role(name='admin', description='Administrator')
        user_datastore.find_or_create_role(name='end-user', description='End user')

        # Create two Users for testing purposes -- unless they already exists.
        # In each case, use Flask-Security utility function to encrypt the password.
        encrypted_password = utils.encrypt_password(app.config['STARTING_ADMIN_PASS'])

        for email in app.config['STARTING_ADMINS']:
            if not user_datastore.get_user(email):
                user_datastore.create_user(email=email, password=encrypted_password)
       

        # Commit any database changes; the User and Roles must exist before we can add a Role to the User
        db.session.commit()

        for email in app.config['STARTING_ADMINS']:
            user_datastore.add_role_to_user(email, 'admin')
            confirmed_admin = user_datastore.get_user(email)
            confirmed_admin.confirmed_at = datetime.utcnow()

        db.session.commit()

        
    @app.before_request
    def before_request():
        """ What we do before every single handled request """
        if current_user.is_authenticated:
            first_time = True if not current_user.last_seen else False
            current_user.last_seen = datetime.utcnow()
            db.session.commit()

    return app


