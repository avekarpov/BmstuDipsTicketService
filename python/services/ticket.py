import logging

import psycopg2

from base import ServiceBase
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
            f'VALUES (\'{user}\', \'{uid}\', \'{flight_number}\', {price}, \'{status}\')'
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


class TicketService(ServiceBase):
    def __init__(
        self, 
        host, 
        port, 
        db_connector, 
        flight_service_host, 
        flight_service_port,
        bonus_service_host,
        bonus_service_port    
    ):
        super().__init__('TicketService', host, port, db_connector)

        self._flight_service_url = f'http://{flight_service_host}:{flight_service_port}'
        self._bonus_service_url = f'http://{bonus_service_host}:{bonus_service_port}'

    # API requests handlers
    ####################################################################################################################

    @ServiceBase.route(path='/api/v1/tickets', methods=['GET', 'POST'])
    def _api_v1_tickets(self):
        method = request.method

        if method == 'GET':
            username = UserValue.get_from(request.headers, 'X-User-Name').value

            table = self._db_connector.get_user_tickets(username)
            
            meesage = []
            for row in table:
                flight = requests.request('GET', f'{self._flight_service_url}/api/v1/flights/{row["flight_number"]}').json()
                if 'error' in flight.keys():
                    raise errors.ServerError(flight, 500)

                meesage.append(
                    {
                        'ticketUid': row['uid'],
                        'fromAirport': flight['fromAirport'],
                        'toAirport': flight['toAirport'],
                        'date': flight['date'],
                        'price': row['price'],
                        'status': row['status']
                    }
                )

            return make_response(meesage, 200)

        if method == 'POST':
            username = UserValue.get_from(request.headers, 'X-User-Name').value

            UserValue.get_from(request.headers, 'Content-Type').rule(rules.json_content)
            body = request.json

            with UserValue.ErrorChain() as error_chain:
                flight_number = UserValue.get_from(body, 'flightNumber', error_chain).expected(str).value
                price = UserValue.get_from(body, 'price', error_chain).expected(int).rule(rules.grater_zero).value
                paid_from_balance = UserValue.get_from(body, 'paidFromBalance', error_chain).expected(bool).value

            flight = requests.request('GET', f'{self._flight_service_url}/api/v1/flights/{flight_number}').json()
            if 'error' in flight.keys():
                raise errors.ServerError(flight, 500)

            price = ServerValue.get_from(flight, 'price').expected(int).rule(rules.grater_zero).value

            privilege = requests.request('GET', f'{self._bonus_service_url}/api/v1/privilege', headers={'X-User-Name': username}).json()
            if 'error' in privilege.keys():
                raise errors.ServerError(privilege, 500)

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
                    'X-User-Name': username
                },
                data=json.dumps({
                    'paidFromBalance': paid_from_balance,
                    'datetime': ServiceBase.get_current_datetime(),
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
                    'data': flight['date'],
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

    @ServiceBase.route(path='/api/v1/tickets/<string:uid>', methods=['GET', 'DELETE'])
    def _api_v1_tickets_aUid(self, uid):
        method = request.method

        if method == 'GET':
            ticket = self._db_connector.get_ticket_by_uid(uid)

            if ticket is None:
                raise errors.UserError({'message': 'non existent ticket'}, 404)

            url_base = f'{self._flight_service_url}/api/v1/flights'

            flight = requests.request('GET', f'{url_base}/{ticket["flight_number"]}').json()

            return make_response(
                {
                    'ticketUid': ticket['uid'],
                    'fromAirport': flight['fromAirport'],
                    'toAirport': flight['toAirport'],
                    'date': flight['date'],
                    'price': ticket['price'],
                    'status': ticket['status']
                },
                200
            )

        if method == 'DELETE':
            username = UserValue.get_from(request.headers, 'X-User-Name').value

            ticket = self._db_connector.get_ticket_by_uid(uid)

            if ticket is None:
                raise errors.UserError({'message': 'non existent ticket'}, 404)

            privilege = requests.request(
                'DELETE',
                f'{self._bonus_service_url}/api/v1/privilege/{uid}',
                headers={
                    'Content-Type': 'application/json',
                    'X-User-Name': username
                }
            )

            if tools.is_json_content(privilege):
                if 'error' in privilege.json().keys():
                    return make_response(privilege, 500)

            self._db_connector.cancel_user_ticket(username, uid)

            return make_response('', 204)

        assert False, 'Invalid request method'

    # Helpers
    ####################################################################################################################

    def _register_routes(self):
        self._register_route('_api_v1_tickets')
        self._register_route('_api_v1_tickets_aUid')


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
        cmd_args.bonus_service_port
    )

    service.run(cmd_args.debug)
