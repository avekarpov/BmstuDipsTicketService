import logging

from base import ServiceBase
from base import DbConnectorBase

import tools

from flask import make_response

import argparse

from threading import Thread

from kafka import KafkaConsumer, TopicPartition

class StatsDbConnector(DbConnectorBase):
    def __init__(self, host, port, database, user, password, sslmode='disable'):
        super().__init__('StatsDbConnector', host, port, database, user, password, sslmode)

    def tick(self, service, method, path):
        query = tools.simplify_sql_query(
            f'INSERT INTO stat(service, method, path, count) '
            f'VALUES(\'{service}\', \'{method}\', \'{path}\', 1) '
            f'ON CONFLICT (service, method, path) DO UPDATE '
            f'SET count = stat.count + 1'
        )
        
        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        cursor.close()
        self._connection.commit()

    def get_stat(self):
        query = tools.simplify_sql_query(
            'select service, method, path, count from stat'
        )
                                         
        self._logger.debug(f'Execute query: {query}')
        cursor = self._connection.cursor()
        cursor.execute(query)

        table = cursor.fetchall()
        cursor.close()
        return [
            { 'endpoint': f'{row[0]} {row[1]} {row[2]}', 'count': row[3] }
            for row in table
        ]

class StatsService(ServiceBase):
    def __init__(self, host, port, db_connector, kafka_consumer: KafkaConsumer):
        super().__init__('StatsService', host, port, db_connector)
        
        self._kafka_consumer = kafka_consumer
        self._kafka_thread = Thread(target=self._kafka_job)

        self._is_running = False
        
    def run(self, *args):
        self._is_running = True
        self._kafka_thread.start()
        super().run(*args)

        self._is_running = False
        self._kafka_thread.join()

    @ServiceBase.route(path='/api/v1/stats', methods=['GET'])
    def _stats(self):
        return make_response(self._db_connector.get_stat(), 200)

    def _register_routes(self):
        self._register_route('_stats')

    def _kafka_job(self):
        self._logger.info('Start kafka consumer job')
        
        self._kafka_consumer.assign(
            [
                TopicPartition('FlightService', 0),
                TopicPartition('TicketService', 0),
                TopicPartition('BounsService', 0),
                TopicPartition('Gateway', 0)
            ]
        )

        while self._is_running:
            try:
                message = self._kafka_consumer.poll(timeout_ms=1000)

                if message == {}:
                    continue

                for key in message:
                    service, _ = key
                    for payload in message[key]:
                        [method, path] = payload.value.decode('utf-8').split(' ')

                self._db_connector.tick(service, method, path)
            except Exception as error:
                # TODO: log error
                pass

        self._logger.info('End kafka consumer job')

if __name__ == '__main__':
    tools.set_basic_logging_config()

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=str, default='localhost')
    parser.add_argument('--port', type=int, default=8040)
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
    
    service = StatsService(
        cmd_args.host,
        cmd_args.port,
        StatsDbConnector(
            cmd_args.db_host,
            cmd_args.db_port,
            cmd_args.db,
            cmd_args.db_user,
            cmd_args.db_password,
            cmd_args.db_sslmode
        ),
        KafkaConsumer(bootstrap_servers=f'{cmd_args.kafka_host}:{cmd_args.kafka_port}')
    )

    service.run(cmd_args.debug)
