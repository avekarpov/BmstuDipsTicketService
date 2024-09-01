from flask import Flask
from flask import make_response
from flask import request

import logging

import psycopg2

from errors import UserError, ServerError
from getters import ServerValue, UserValue

from datetime import datetime
import time

from keycloak import KeycloakOpenID
from keycloak.keycloak_openid import jwt

from kafka import KafkaProducer

class DbConnectorBase:
    def __init__(self, name, host, port, database, user, password, sslmode):
        self._logger = logging.getLogger(name)

        self._connection = self.create_connection(host, port, database, user, password, sslmode)

    def create_connection(self, host, port, database, user, password, sslmode, retry_number=10, reconnecting_delay_s=1):
        self._logger.info(
            f'Create connection on \'http://{host}:{port}\' to database \'{database}\' under user \'{user}\''
        )

        for i in range(retry_number):
            try:
                return psycopg2.connect(
                    host=host,
                    port=port,
                    database=database,
                    user=user,
                    password=password,
                    sslmode=sslmode
                )
            except Exception as exception:
                error = exception.args[0].replace('\n', ' ').strip()
                if error.find('Connection refused'):
                    logging.debug(f'Got error {error}, reconnecting in {reconnecting_delay_s} seconds')
                    time.sleep(reconnecting_delay_s)
        
        raise RuntimeError('Connection to database failed')


class ServiceBase:
    def __init__(self, name, host, port, db_connector:DbConnectorBase=None, kafka_producer:KafkaProducer=None):
        self._service_name = name

        self._host = host
        self._port = port
        self._db_connector = db_connector
        self._kafka_producer = kafka_producer

        self._flask_app = Flask(f'{self._service_name} flask')

        self._logger = logging.getLogger(self._service_name)

        self._register_manage_health()
        self._register_routes()

    def run(self, debug=False):
        self._logger.info(f'Run service on http://{self._host}:{self._port}')

        try:
            self._logger.info(f'Run flask app: host: {self._host}, port: {self._port}, debug: {debug}')

            self._flask_app.run(self._host, self._port, debug=debug, use_reloader=False)

            self._logger.info(f'End flask app run')

        except Exception as exception:
            self._logger.error(f'Failed while run flask app, error: {exception}')

            raise
        except:
            self._logger.error(f'Failed while run flask app, with unknown error')

            raise
            

        self._logger.info(f'End service run')

    def _manage_health(self):
        return make_response()
    
    def _register_manage_health(self):
        path = '/manage/health'
        methods = ['GET']

        self._logger.info(f'Register route for \'{path}\' with methods: {methods}')

        self._flask_app.add_url_rule(
            path,
            view_func=self._manage_health,
            methods=methods
        )

    def _register_routes(self):
        pass

    def _register_route(self, handler):
        handler = getattr(self, handler)

        self._logger.info(f'Register route for \'{handler.path}\' with methods: {handler.methods}')

        self._flask_app.add_url_rule(
            handler.path,
            view_func=handler,
            methods=handler.methods
        )

    @staticmethod
    def get_current_datetime():
        return datetime.today().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def route(path, methods):
        def decorate(func):
            def wrapper(self, *args, **kwargs):
                self._logger.debug(f'Call handler for path: {path}')

                try:
                    method = request.method
                    
                    if self._kafka_producer is not None:
                        payload = f'{method} {path}'.encode('utf-8')
                        
                        self._logger.debug(f'Send {payload} to {self._service_name} topic')
                        
                        self._kafka_producer.send(
                            self._service_name,
                            value=payload,
                            partition=0
                        )
                        # self._kafka_producer.flush()
                    
                    return func(self=self, *args, **kwargs)

                except UserError as error:
                    return make_response(error.message, error.code)

                except ServerError as error:
                    self._logger.error(f'Server internal error: {error.message["message"]} with code {error.code}')

                    return make_response({'message': 'internal error'}, error.code)

                except Exception as error:
                    self._logger.error(f'Unknown internal error: {error}')
                    
                    return make_response({'message': 'internal error'}, 500)

            setattr(wrapper, 'path', path)
            setattr(wrapper, 'methods', methods)

            wrapper.__name__ = func.__name__
            return wrapper

        return decorate

    @staticmethod
    def _get_json_from(response):
        if 400 <= response.status_code <= 499:
                raise UserError(response.json(), response.status_code)

        if 500 <= response.status_code:
            raise ServerError(response.json(), response.status_code)
        
        return response.json()


class ServerBaseWithKeycloak(ServiceBase):
    realm_name='master'
    
    def __init__(
        self,
        keycloak_url,
        keycloak_client_id,
        keycloak_client_secret,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        
        self._keycloak_openid = KeycloakOpenID(
            server_url=keycloak_url,
            client_id=keycloak_client_id,
            client_secret_key=keycloak_client_secret,
            realm_name=self.realm_name
        )

    def _get_user_token_by(self, username, password):
        return ServerValue.get_from(self._keycloak_openid.token(username=username, password=password), 'access_token').value

    def _get_user_token_from(self, request):
        token = UserValue.get_from(request.headers, 'Authorization', code=401).value.split()

        if len(token) > 1:
            token = token[1]
        else:
            token = token[0]

        self._validate_token(token)

        return token

    def _get_username_by(self, token):
        try:
            return ServerValue.get_from(self._keycloak_openid.userinfo(token), 'preferred_username').value

        except Exception as error:
            self._logger.error(f'Failed get username with error: {error}')

            raise UserError('invalid token', 401)

    def _validate_token(self, token):
        def raise_invalid_token(error, message='invalid token'):
            self._logger.error(f'Failed decode token with error: {error}')
            
            raise UserError(message, 401)

        try:
            self._keycloak_openid.decode_token(token)

        except jwt.JWTExpired as error:
            raise_invalid_token(error, 'token experid')

        except Exception as error:
            raise_invalid_token(error)
