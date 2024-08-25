import logging

from base import ServerBaseWithKeycloak
from getters import UserValue
from errors import UserError
import tools

import requests

from flask import request as flask_request
from flask import make_response

import argparse

from time import time

from keycloak import KeycloakAdmin
from keycloak import KeycloakPostError

class ServiceInfo:
    def __init__(self, url):
        self.url = url
        self.queue = []
        self.error_level = 0
        self.last_error_time = 0

ALL_METHODS = ['GET', 'POST', 'DELETE']


class Gateway(ServerBaseWithKeycloak):
    def __init__(
        self, 
        host, port, 
        flight_service_host, flight_service_port,
        ticket_service_host, ticket_service_port,
        bonus_service_host, bonus_service_port,
        valid_error_level, wait_before_retry,
        keycloak_host,
        keycloak_port,
        keycloak_client_id,
        keycloak_client_secret,
        keycloak_admin_username,
        keycloak_admin_password,
        authorization_required=True # enable authorization check
    ):
        keycloak_url = f'http://{keycloak_host}:{keycloak_port}'
        
        super().__init__(
            keycloak_url,
            keycloak_client_id,
            keycloak_client_secret,
            'Gateway', 
            host,
            port
        )

        self._flight_service_info = ServiceInfo(f'http://{flight_service_host}:{flight_service_port}')
        self._ticket_service_info = ServiceInfo(f'http://{ticket_service_host}:{ticket_service_port}')
        self._bonus_service_info = ServiceInfo(f'http://{bonus_service_host}:{bonus_service_port}')

        self._valid_error_level = valid_error_level
        self._wait_before_retry = wait_before_retry

        self._keycloak_admin = KeycloakAdmin(
            server_url=keycloak_url,
            username=keycloak_admin_username,
            password=keycloak_admin_password,
            realm_name='master'
        )

        self._authorization_required = authorization_required

    ################################################################################################

    @ServerBaseWithKeycloak.route(path='/api/v1/flights', methods=ALL_METHODS)
    def _flight(self):
        return self._resend(
            self._flight_service_info, f'/api/v1/flights', flask_request
        )

    @ServerBaseWithKeycloak.route(path='/api/v1/flights/<path:path>', methods=ALL_METHODS)
    def _flight_aPath(self, path):
        return self._resend(
            self._flight_service_info, f'/api/v1/flights/{path}', flask_request
        )
    
    ################################################################################################
    
    @ServerBaseWithKeycloak.route(path='/api/v1/privilege', methods=ALL_METHODS)
    def _privilege(self):
        return self._resend(
            self._bonus_service_info, f'/api/v1/privilege', flask_request
        )

    @ServerBaseWithKeycloak.route(path='/api/v1/privilege/<path:path>', methods=ALL_METHODS)
    def _privilege_aPath(self, path):
        return self._resend(
            self._bonus_service_info, f'/api/v1/privilege/{path}', flask_request
        )   
        
    ################################################################################################

    @ServerBaseWithKeycloak.route(path='/api/v1/tickets', methods=ALL_METHODS)
    def _tickets(self):
        return self._resend(
            self._ticket_service_info, f'/api/v1/tickets', flask_request
        )

    @ServerBaseWithKeycloak.route(path='/api/v1/tickets/<path:path>', methods=ALL_METHODS)
    def _tickets_aPath(self, path):
        return self._resend(
            self._ticket_service_info, f'/api/v1/tickets/{path}', flask_request
        )   
    
    @ServerBaseWithKeycloak.route(path='/api/v1/me', methods=ALL_METHODS)
    def _me(self):
        return self._resend(
            self._ticket_service_info, f'/api/v1/me', flask_request
        )

    ################################################################################################

    @ServerBaseWithKeycloak.route(path='/api/v1/authorize', methods=['POST'])
    def _authorize(self):
        request = flask_request

        with UserValue.ErrorChain() as error_chain:
            username = UserValue.get_from(request.json, 'username', error_chain).expected(str).value
            password = UserValue.get_from(request.json, 'password', error_chain).expected(str).value

        return make_response(self._get_user_token_by(username, password), 200)

    @ServerBaseWithKeycloak.route(path='/api/v1/register', methods=['POST'])
    def _register(self):
        request = flask_request

        with UserValue.ErrorChain() as error_chain:
            username = UserValue.get_from(request.json, 'username', error_chain).expected(str).value
            password = UserValue.get_from(request.json, 'password', error_chain).expected(str).value

        try:
            self._keycloak_admin.create_user(
                {
                    'username': username,
                    'enabled': True,
                    'credentials': [{'value': password, 'type': 'password'}]
                }
            )

        except KeycloakPostError as error:
            if error.response_code == 409:
                raise UserError('already used username', 409)
        
        return make_response(self._get_user_token_by(username, password), 200)

    @ServerBaseWithKeycloak.route(path='/api/v1/callback', methods=ALL_METHODS)
    def _callback(self):
        return make_response('', 200)

    ################################################################################################

    def _resend(self, service_info, path, request):
        if self._authorization_required:
            self._get_user_token_from(request)
        else:
            self._logger.warn("Authorization check disabled")

        try:
            if len(service_info.queue) != 0:
                if not self._check_service_health(service_info):
                    raise RuntimeError('Service is unavailable')

                for request_backup in service_info.queue:
                    self._request(service_info, request_backup.path, request_backup)
                    service_info.queue.remove(request_backup)

            return self._request(service_info, path, request)
        
        except Exception:
            if request.method == 'DELETE':
                class RequestBackup:
                    def __init__(self, path, method, headers, args, data):
                        self.path = path
                        self.method = method
                        self.headers = headers
                        self.args = args
                        self.data = data

                service_info.queue.append(RequestBackup(path, request.method, request.headers, request.args, request.data))

                return make_response('', 200)
            
        return make_response('Internal server error', 500)

    def _request(self, service_info, path, request):
        method = request.method

        try:
            self._logger.debug('Send request')
            response = requests.request(
                method,
                f'{service_info.url}{path}',
                headers=request.headers,
                params=request.args,
                data=request.data
            )

            service_info.error_level = 0
            self._logger.debug(f'Got response from service, reset error level to 0')

            if tools.is_json_content(response):
                return make_response(response.json(), response.status_code)

            return make_response(response.text, response.status_code)

        except Exception as error:
            self._logger.error(f'Failed to send request, error: {error}')

            service_info.error_level = min(service_info.error_level, self._valid_error_level) + 1
            self._logger.debug(f'Error level: {service_info.error_level}')
            self._last_error_time = int(time())

            raise

    def _check_service_health(self, service_info: ServiceInfo):
        if service_info.error_level > self._valid_error_level:
            if service_info.last_error_time + self._wait_before_retry > int(time()):
                self._logger.error(
                    f'Failed to send request to {service_info.url}, '
                    f'error level {service_info.error_level} > {self._valid_error_level} '
                    f'for {self._wait_before_retry}s from last {service_info.last_error_time}'
                )
            
                return False
         
        try:
            requests.request('GET', f'{service_info.url}/manage/health')

        except:
            return False
        
        return True

    # Helpers
    ####################################################################################################################

    def _register_routes(self):
        self._register_route('_flight')
        self._register_route('_flight_aPath')
        self._register_route('_privilege')
        self._register_route('_privilege_aPath')
        self._register_route('_tickets')
        self._register_route('_tickets_aPath')
        self._register_route('_me')
        self._register_route('_authorize')
        self._register_route('_callback')
        self._register_route('_register')


if __name__ == '__main__':
    tools.set_basic_logging_config()

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='localhost')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--flight-service-host', type=str, default='localhost')
    parser.add_argument('--flight-service-port', type=int, default=8060)
    parser.add_argument('--bonus-service-host', type=str, default='localhost')
    parser.add_argument('--bonus-service-port', type=int, default=8050)
    parser.add_argument('--ticket-service-host', type=str, default='localhost')
    parser.add_argument('--ticket-service-port', type=int, default=8070)
    parser.add_argument('--valid-error-level', type=int, default=10)
    parser.add_argument('--wait-before-retry', type=int, default=10)
    parser.add_argument('--oidc-host', type=str, default='localhost')
    parser.add_argument('--oidc-port', type=int, default=8030)
    parser.add_argument('--oidc-client-id', type=str, default='ticket-service')
    parser.add_argument('--oidc-client-secret', type=str, required=True)
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--no-authorization', action='store_true')

    cmd_args = parser.parse_args()

    if cmd_args.debug:
        tools.set_basic_logging_config(level=logging.DEBUG)
    else:
        tools.set_basic_logging_config(level=logging.INFO)
        
    if cmd_args.no_authorization and not cmd_args.debug:
        raise RuntimeError('"no-authorization" option could be enabled only with "debug" option')

    gateway = Gateway(
        cmd_args.host,
        cmd_args.port,
        cmd_args.flight_service_host,
        cmd_args.flight_service_port,
        cmd_args.ticket_service_host,
        cmd_args.ticket_service_port,
        cmd_args.bonus_service_host,
        cmd_args.bonus_service_port,
        cmd_args.valid_error_level,
        cmd_args.wait_before_retry,
        cmd_args.oidc_host,
        cmd_args.oidc_port,
        cmd_args.oidc_client_id,
        cmd_args.oidc_client_secret,
        'admin',
        'admin',
        not cmd_args.no_authorization
    )

    gateway.run(cmd_args.debug)
