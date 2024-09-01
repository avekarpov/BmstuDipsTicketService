import logging

from base import ServiceBase
from base import DbConnectorBase

import tools
import errors
import rules
from getters import UserValue

from flask import request
from flask import make_response

import argparse

from kafka import KafkaProducer

class FlightDbConnector(DbConnectorBase):
    def __init__(self, host, port, database, user, password, sslmode='disable'):
        super().__init__('FlightDbConnector', host, port, database, user, password, sslmode)

    def get_flights(self, page_number, page_size):
        query = tools.simplify_sql_query(
            f'SELECT id, number, datetime, price, from_airport, to_airport FROM('
            f'    SELECT '
            f'        flight.id, '
            f'        number, '
            f'        datetime, '
            f'        price, '
            f'        CONCAT(from_airport.city, \' \' , from_airport.name) as from_airport, '
            f'        CONCAT(to_airport.city, \' \', to_airport.name) as to_airport, '
            f'        ROW_NUMBER() OVER (ORDER BY flight.id) as row '
            f'    FROM flight '
            f'    JOIN airport as from_airport ON flight.from_airport_id = from_airport.id '
            f'    JOIN airport as to_airport ON flight.to_airport_id = to_airport.id'
            f') as flight_with_row '
            f'WHERE {(page_number - 1) * page_size + 1} <= row AND row < {page_number * page_size + 1}'
        )

        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        table = cursor.fetchall()
        cursor.close()

        return [
            {
                'id': row[0],
                'number': row[1],
                'datetime': row[2],
                'price': row[3],
                'from_airport': row[4],
                'to_airport': row[5]
            }
            for row in table
        ]

    def get_flight_by_number(self, number):
        query = tools.simplify_sql_query(
            f'SELECT id, number, datetime, price, from_airport, to_airport FROM('
            f'    SELECT '
            f'        flight.id, '
            f'        number, '
            f'        datetime, '
            f'        price, '
            f'        CONCAT(from_airport.city, \' \' , from_airport.name) as from_airport, '
            f'        CONCAT(to_airport.city, \' \', to_airport.name) as to_airport '
            f'    FROM flight '
            f'    JOIN airport as from_airport ON flight.from_airport_id = from_airport.id '
            f'    JOIN airport as to_airport ON flight.to_airport_id = to_airport.id'
            f') as flight_with_airport '
            f'WHERE number = \'{number}\''
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
            'number': row[1],
            'datetime': row[2],
            'price': row[3],
            'from_airport': row[4],
            'to_airport': row[5]
        }


class FlightService(ServiceBase):
    def __init__(self, host, port, db_connector, kafka_producer):
        super().__init__('FlightService', host, port, db_connector, kafka_producer)

    # API requests handlers
    ####################################################################################################################

    @ServiceBase.route('/api/v1/flights', ['GET'])
    def _api_v1_flights(self):
        method = request.method

        if method == 'GET':

            with UserValue.ErrorChain() as error_chain:
                page_number = UserValue.get_from(request.args, 'page', error_chain).cast_to_int().rule(rules.grater_zero).value
                page_size = UserValue.get_from(request.args, 'size', error_chain).cast_to_int().rule(rules.grater_zero).value

            table = self._db_connector.get_flights(page_number, page_size)

            return make_response(
                {
                    'page': page_number,
                    'pageSize': page_size,
                    'totalElements': len(table),
                    'items': [
                        {
                            'flightNumber': row['number'],
                            'fromAirport': row['from_airport'],
                            'toAirport': row['to_airport'],
                            'date': row['datetime'],
                            'price': row['price']
                        }
                        for row in table
                    ]
                },
                200
            )

        assert False, 'Invalid request method'

    @ServiceBase.route('/api/v1/flights/<string:number>', ['GET'])
    def _api_v1_flights_aNumber(self, number):
        method = request.method

        if method == 'GET':
            flight = self._db_connector.get_flight_by_number(number)

            if flight is None:
                raise errors.UserError('non existent flight', 404)

            return make_response(
                {
                    'flightNumber': flight['number'],
                    'fromAirport': flight['from_airport'],
                    'toAirport': flight['to_airport'],
                    'date': flight['datetime'],
                    'price': flight['price']
                },
                200
            )

        assert False, 'Invalid request method'

    # Helpers
    ####################################################################################################################

    def _register_routes(self):
        self._register_route('_api_v1_flights')
        self._register_route('_api_v1_flights_aNumber')


if __name__ == '__main__':
    tools.set_basic_logging_config()

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='localhost')
    parser.add_argument('--port', type=int, default=8060)
    parser.add_argument('--db-host', type=str, default='localhost')
    parser.add_argument('--db-port', type=int, default=5432)
    parser.add_argument('--db', type=str, default='flights')
    parser.add_argument('--db-user', type=str, required=True)
    parser.add_argument('--db-password', type=str, required=True)
    parser.add_argument('--db-sslmode', type=str, default='disable')
    parser.add_argument('--kafka-host', type=str, default='localhost')
    parser.add_argument('--kafka-port', type=str, default=29092)
    parser.add_argument('--debug', action='store_true')

    cmd_args = parser.parse_args()

    if cmd_args.debug:
        tools.set_basic_logging_config(level=logging.DEBUG)
    else:
        tools.set_basic_logging_config(level=logging.INFO)

    service = FlightService(
        cmd_args.host,
        cmd_args.port,
        FlightDbConnector(
            cmd_args.db_host,
            cmd_args.db_port,
            cmd_args.db,
            cmd_args.db_user,
            cmd_args.db_password,
            cmd_args.db_sslmode
        ),
        KafkaProducer(bootstrap_servers=f'{cmd_args.kafka_host}:{cmd_args.kafka_port}')
    )

    service.run(cmd_args.debug)
