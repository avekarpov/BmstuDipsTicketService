import logging

from base import ServerBaseWithKeycloak
from base import DbConnectorBase

from flask import request
from flask import make_response

import argparse

import requests

import uuid
import json

import tools
import errors
import rules
from getters import UserValue
from getters import ServerValue

from kafka import KafkaProducer

class TicketDbConnector(DbConnectorBase):
    def __init__(self, host, port, database, user, password, sslmode='disable'):
        super().__init__('TicketDbConnector', host, port, database, user, password, sslmode)

    def get_user_tickets(self, user):
        query = tools.simplify_sql_query(
            f'SELECT id, uid, username, flight_number, price, status FROM ticket WHERE username = \'{user}\''
        )

        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        table = cursor.fetchall()
        cursor.close()

        return [
            {
                'id': row[0],
                'uid': row[1],
                'username': row[2],
                'flight_number': row[3],
                'price': row[4],
                'status': row[5]
            }
            for row in table
        ]

    def get_ticket_by_uid(self, uid):
        query = tools.simplify_sql_query(
            f'SELECT id, uid, username, flight_number, price, status FROM ticket WHERE uid = \'{uid}\''
        )

        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        row = cursor.fetchone()
        cursor.close()

        if row is None:
            return None

        return {
            'id': row[0],
            'uid': row[1],
            'username': row[2],
            'flight_number': row[3],
            'price': row[4],
            'status': row[5]
        }

    def add_user_ticket(self, user, uid, flight_number, price, status):
        query = tools.simplify_sql_query(
            f'INSERT INTO ticket(username, uid, flight_number, price, status) '
            f'VALUES(\'{user}\', \'{uid}\', \'{flight_number}\', {price}, \'{status}\')'
        )

        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        cursor.close()
        self._connection.commit()

    def cancel_user_ticket(self, user, uid):
        query = tools.simplify_sql_query(
            f'UPDATE ticket SET status = \'CANCELED\' WHERE username = \'{user}\' AND uid = \'{uid}\''
        )

        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        cursor.close()
        self._connection.commit()


    def get_flight_tickets_count(self, flight_number):
        query = tools.simplify_sql_query(
            f'SELECT COUNT(1) FROM ticket WHERE flight_number = \'{flight_number}\' and status = \'PAID\''
        )
        
        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        row = cursor.fetchone()
        cursor.close()
        
        return row[0]

class TicketService(ServerBaseWithKeycloak):
    def __init__(
        self, 
        host, 
        port, 
        db_connector, 
        flight_service_host, 
        flight_service_port,
        bonus_service_host,
        bonus_service_port,
        keycloak_host,
        keycloak_port,
        keycloak_client_id,
        keycloak_client_secret,
        kafka_producer
    ):
        super().__init__(
            f'http://{keycloak_host}:{keycloak_port}',
            keycloak_client_id,
            keycloak_client_secret,
            'TicketService', 
            host, 
            port, 
            db_connector,
            kafka_producer
        )

        self._flight_service_url = f'http://{flight_service_host}:{flight_service_port}'
        self._bonus_service_url = f'http://{bonus_service_host}:{bonus_service_port}'

    # API requests handlers
    ####################################################################################################################

    @ServerBaseWithKeycloak.route(path='/api/v1/tickets', methods=['GET', 'POST'])
    def _api_v1_tickets(self):
        method = request.method

        if method == 'GET':
            token = self._get_user_token_from(request)
            username = self._get_username_by(token)

            table = self._db_connector.get_user_tickets(username)
            
            meesage = []
            for row in table:
                flight = requests.request('GET', f'{self._flight_service_url}/api/v1/flights/{row["flight_number"]}', headers={'Authorization': f'Bearer {token}'}).json()
                if 'error' in flight.keys():
                    raise errors.ServerError(flight, 500)

                meesage.append(
                    {
                        'ticketUid': row['uid'],
                        'fromAirport': flight['fromAirport'],
                        'toAirport': flight['toAirport'],
                        'date': flight['date'],
                        'price': row['price'],
                        'status': row['status'],
                        'flightNumber': flight['flightNumber']
                    }
                )

            return make_response(meesage, 200)

        if method == 'POST':
            token = self._get_user_token_from(request)
            username = self._get_username_by(token)

            UserValue.get_from(request.headers, 'Content-Type').rule(rules.json_content)
            body = request.json

            with UserValue.ErrorChain() as error_chain:
                flight_number = UserValue.get_from(body, 'flightNumber', error_chain).expected(str).value
                price = UserValue.get_from(body, 'price', error_chain).expected(int).rule(rules.grater_zero).value
                paid_from_balance = UserValue.get_from(body, 'paidFromBalance', error_chain).expected(bool).value
 
            count = self._db_connector.get_flight_tickets_count(flight_number)

            if count >= 3:
                raise errors.UserError('flight is full', 409)

            flight = self._get_json_from(
                requests.request(
                    'GET', 
                    f'{self._flight_service_url}/api/v1/flights/{flight_number}',
                    headers={'Authorization': f'Bearer {token}'}
                )
            )

            price = ServerValue.get_from(flight, 'price').expected(int).rule(rules.grater_zero).value

            privilege = self._get_json_from(
                requests.request(
                    'GET', 
                    f'{self._bonus_service_url}/api/v1/privilege',
                    headers={'Authorization': f'Bearer {token}'}
                )
            )

            bonus_balance = ServerValue.get_from(privilege, 'balance').expected(int).rule(rules.greate_equal_zero).value
            
            if bonus_balance == 0:
                paid_from_balance = False

            if paid_from_balance:
                paid_by_bonuses = min(price, bonus_balance)
                balance_diff = paid_by_bonuses
            else:
                paid_by_bonuses = 0
                balance_diff = int(price / 10)
                
            paid_by_money = price - bonus_balance

            uid = str(uuid.uuid4())

            privilege = requests.request(
                'POST',
                f'{self._bonus_service_url}/api/v1/privilege/{uid}',
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {token}'
                },
                data=json.dumps({
                    'paidFromBalance': paid_from_balance,
                    'datetime': ServerBaseWithKeycloak.get_current_datetime(),
                    'ticketUid': uid,
                    'balanceDiff': balance_diff
                })
            ).json()

            if 'error' in privilege.keys():
                return make_response(privilege, 500)

            self._db_connector.add_user_ticket(username, uid, flight_number, price, 'PAID')

            return make_response(
                {
                    'ticketUid': uid,
                    'flightNumber': flight_number,
                    'fromAirport': flight['fromAirport'],
                    'toAirport': flight['toAirport'],
                    'date': flight['date'],
                    'price': price,
                    'paidByMoney': paid_by_money,
                    'paidByBonuses': paid_by_bonuses,
                    'status': 'PAID',
                    'privilege': {
                        'balance': privilege['balance'],
                        'status': privilege['status']
                    }
                },
                200
            )

        assert False, 'Invalid request method'

    @ServerBaseWithKeycloak.route(path='/api/v1/tickets/<string:uid>', methods=['GET', 'DELETE'])
    def _api_v1_tickets_aUid(self, uid):
        method = request.method

        if method == 'GET':
            token = self._get_user_token_from(request)

            ticket = self._db_connector.get_ticket_by_uid(uid)

            if ticket is None:
                raise errors.UserError('non existent ticket', 404)

            url_base = f'{self._flight_service_url}/api/v1/flights'

            flight = requests.request('GET', f'{url_base}/{ticket["flight_number"]}', headers={'Authorization': f'Bearer {token}'}).json()

            return make_response(
                {
                    'ticketUid': ticket['uid'],
                    'fromAirport': flight['fromAirport'],
                    'toAirport': flight['toAirport'],
                    'date': flight['date'],
                    'price': ticket['price'],
                    'status': ticket['status'],
                    'flightNumber': flight['flightNumber']
                },
                200
            )

        if method == 'DELETE':
            token = self._get_user_token_from(request)
            username = self._get_username_by(token)

            ticket = self._db_connector.get_ticket_by_uid(uid)

            if ticket is None:
                raise errors.UserError('non existent ticket', 404)

            privilege = requests.request(
                'DELETE',
                f'{self._bonus_service_url}/api/v1/privilege/{uid}',
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {token}'
                }
            )

            if tools.is_json_content(privilege):
                if 'error' in privilege.json().keys():
                    return make_response(privilege, 500)

            self._db_connector.cancel_user_ticket(username, uid)

            return make_response('', 204)

        assert False, 'Invalid request method'

    @ServerBaseWithKeycloak.route(path='/api/v1/me', methods=['GET'])    
    def _api_v1_me(self):
        method = request.method

        if method == 'GET':
            token = self._get_user_token_from(request)
            username = self._get_username_by(token)

            privilege = requests.request('GET', f'{self._bonus_service_url}/api/v1/privilege', headers={'Authorization': f'Bearer {token}'}).json()
            if 'error' in privilege.keys():
                raise errors.ServerError(privilege, 500)

            table = self._db_connector.get_user_tickets(username)
            
            ticktes = []
            for row in table:
                flight = requests.request('GET', f'{self._flight_service_url}/api/v1/flights/{row["flight_number"]}', headers={'Authorization': f'Bearer {token}'}).json()
                if 'error' in flight.keys():
                    raise errors.ServerError(flight, 500)

                ticktes.append(
                    {
                        'ticketUid': row['uid'],
                        'fromAirport': flight['fromAirport'],
                        'toAirport': flight['toAirport'],
                        'date': flight['date'],
                        'price': row['price'],
                        'status': row['status'],
                        'flightNumber': flight['flightNumber']
                    }
                )
            message = {
                'tickets': ticktes,
                'privilege': privilege
            }

            return make_response(message, 200)

        assert False, 'Invalid request method'

    # Helpers
    ####################################################################################################################

    def _register_routes(self):
        self._register_route('_api_v1_tickets')
        self._register_route('_api_v1_tickets_aUid')
        self._register_route('_api_v1_me')


if __name__ == '__main__':
    tools.set_basic_logging_config()

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='localhost')
    parser.add_argument('--port', type=int, default=8070)
    parser.add_argument('--flight-service-host', type=str, default='localhost')
    parser.add_argument('--flight-service-port', type=int, default=8060)
    parser.add_argument('--bonus-service-host', type=str, default='localhost')
    parser.add_argument('--bonus-service-port', type=int, default=8050)
    parser.add_argument('--db-host', type=str, default='localhost')
    parser.add_argument('--db-port', type=int, default=5432)
    parser.add_argument('--db', type=str, default='tickets')
    parser.add_argument('--db-user', type=str, required=True)
    parser.add_argument('--db-password', type=str, required=True)
    parser.add_argument('--db-sslmode', type=str, default='disable')
    parser.add_argument('--oidc-host', type=str, default='localhost')
    parser.add_argument('--oidc-port', type=int, default=8030)
    parser.add_argument('--oidc-client-id', type=str, default='ticket-service')
    parser.add_argument('--oidc-client-secret', type=str, required=True)
    parser.add_argument('--kafka-host', type=str, default='localhost')
    parser.add_argument('--kafka-port', type=str, default=29092)
    parser.add_argument('--debug', action='store_true')

    cmd_args = parser.parse_args()

    if cmd_args.debug:
        tools.set_basic_logging_config(level=logging.DEBUG)
    else:
        tools.set_basic_logging_config(level=logging.INFO)

    service = TicketService(
        cmd_args.host,
        cmd_args.port,
        TicketDbConnector(
            cmd_args.db_host,
            cmd_args.db_port,
            cmd_args.db,
            cmd_args.db_user,
            cmd_args.db_password,
            cmd_args.db_sslmode
        ),
        cmd_args.flight_service_host,
        cmd_args.flight_service_port,
        cmd_args.bonus_service_host,
        cmd_args.bonus_service_port,
        cmd_args.oidc_host,
        cmd_args.oidc_port,
        cmd_args.oidc_client_id,
        cmd_args.oidc_client_secret,
        KafkaProducer(bootstrap_servers=f'{cmd_args.kafka_host}:{cmd_args.kafka_port}'),
    )

    service.run(cmd_args.debug)
