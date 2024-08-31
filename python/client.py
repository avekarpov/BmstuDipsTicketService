import requests
import json
import argparse
from datetime import datetime
from services import tools
from tabulate import tabulate


class Client:
    def __init__(self, host, port, username, password):
        self._url = f'http://{host}:{port}'

        self._username = username
        self._password = password

        self._token = self.authorize()

    def health(self):
        response = requests.request(
            'GET',
            f'{self._url}/manage/health'
        )

        self._check_ok(response)

        return 'Healthed'

    def authorize(self):
        response = requests.request(
            'POST',
            self._build_enpoint('authorize'),
            headers=self._json_header(),
            data=json.dumps(
                {
                    'username': self._username,
                    'password': self._password
                }
            )
        )

        self._check_ok(response)

        return response.text

    def register(self, username, password):
        response = requests.request(
            'POST',
            self._build_enpoint('register'),
            headers={
                **self._json_header(),
                **self._authorization_header()
            },
            data=json.dumps(
                {
                    'username': username,
                    'password': password
                }
            )
        )

        self._check_ok(response)

        return 'registered'

    def flights(self, page, size=50):
        response = requests.request(
            'GET',
            self._build_enpoint('flights'),
            headers=self._authorization_header(),
            params={'page': page, 'size': size}
        )

        self._check_ok(response)
        self._check_json(response)

        page = response.json()['page']

        headers = [
            'дата', 
            'номер рейса', 
            'аэропорт вылета', 
            'аэропорт прилета',
            'цена'
        ]
        data = [
            [
                self._cut_datetime(i['date']),
                i['flightNumber'], 
                i['fromAirport'], 
                i['toAirport'], 
                i['price']
            ]
            for i in response.json()['items']
        ]

        return \
            f'{tabulate(data, headers, "heavy_outline")}\n' \
            f'страница: {page}'

    def flight(self, number):
        response = requests.request(
            'GET',
            self._build_enpoint(f'flights/{number}'),
            headers=self._authorization_header(),
        )

        self._check_ok(response)
        self._check_json(response)

        headers = [
            'дата', 
            'номер рейса', 
            'аэропорт вылета', 
            'аэропорт прилета',
            'цена'
        ]
        data = [
            [
                self._cut_datetime(response.json()['date']),
                response.json()['flightNumber'], 
                response.json()['fromAirport'], 
                response.json()['toAirport'], 
                response.json()['price']
            ]
        ]
        
        return f'{tabulate(data, headers, "heavy_outline")}\n'

    def tickets(self):
        response = requests.request(
            'GET',
            self._build_enpoint('tickets'),
            headers=self._authorization_header()
        )

        self._check_ok(response)
        self._check_json(response)
    
        headers = [
            'номер билета',
            'дата',
            'номер рейса', 
            'аэропорт вылета', 
            'аэропорт прилета',
            'статус',
            'цена'
        ]
        data = [
            [
                i['ticketUid'][:6], 
                self._cut_datetime(i['date']),
                i['flightNumber'], 
                i['fromAirport'], 
                i['toAirport'], 
                self._pretty_status(i['status']), 
                i['price']
            ]
            for i in response.json()
        ]

        return f'{tabulate(data, headers, "heavy_outline")}\n'

    def ticket(self, ticket_number):
        response = requests.request(
            'GET',
            self._build_enpoint(f'tickets/{self._get_full_ticket_number(ticket_number)}'),
            headers={
                **self._json_header(),
                **self._authorization_header()
            }
        )
        
        self._check_ok(response)
        self._check_json(response)
    
        headers = [
            'номер билета',
            'дата',
            'номер рейса', 
            'аэропорт вылета', 
            'аэропорт прилета',
            'статус',
            'цена'
        ]
        data = [
            [
                response.json()['ticketUid'][:6],
                self._cut_datetime(response.json()['date']),
                response.json()['flightNumber'], 
                response.json()['fromAirport'], 
                response.json()['toAirport'], 
                self._pretty_status(response.json()['status']),
                response.json()['price']
            ]
        ]

        return f'{tabulate(data, headers, "heavy_outline")}\n'

    def buy_ticket(self, flight_number, paid_from_balance):
        response = requests.request(
            'POST',
            self._build_enpoint('tickets'),
            headers={
                **self._json_header(),
                **self._authorization_header()
            },
            data=json.dumps(
                {
                    'flightNumber': flight_number,
                    'price': 1,  # server doesn't use it
                    'paidFromBalance': paid_from_balance
                }
            )
        )

        self._check_ok(response)
        self._check_json(response)
    
        headers = [
            'номер билета',
            'дата',
            'номер рейса', 
            'аэропорт вылета', 
            'аэропорт прилета',
            'статус',
            'цена'
        ]
        data = [
            [
                response.json()['ticketUid'][:6],
                self._cut_datetime(response.json()['date']),
                response.json()['flightNumber'], 
                response.json()['fromAirport'], 
                response.json()['toAirport'], 
                self._pretty_status(response.json()['status']), 
                response.json()['price']
            ]
        ]

        return \
            f'билет\n{tabulate(data, headers, "heavy_outline")}\n' \
            f'оплачено бонусами: {response.json()["paidByBonuses"]}\n' \
            f'баланс: {response.json()["privilege"]["balance"]}\n'

    def return_ticket(self, ticket_number):
        response = requests.request(
            'DELETE',
            self._build_enpoint(f'tickets/{self._get_full_ticket_number(ticket_number)}'),
            headers={
                **self._json_header(),
                **self._authorization_header()
            }
        )
        
        self._check_ok(response, code=204)
        
        return 'returned'

    def me(self):
        response = requests.request(
            'GET',
            self._build_enpoint('me'),
            headers=self._authorization_header()
        )
        
        self._check_ok(response)
        self._check_json(response)
        
        privilege_history_headers = [
            'номер билета',
            'дата',
            'изменение баланса'
        ]

        privilege_history_data = [
            [
                i['ticketUid'][:6],
                self._cut_datetime(i['date']),
                f'{"+" if i["operationType"] == "FILL_IN_BALANCE" else "-"}{i["balanceDiff"]}'
            ]
            for i in response.json()['privilege']['history']
        ]

        tickes_headers = [
            'номер билета',
            'дата',
            'номер рейса', 
            'аэропорт вылета', 
            'аэропорт прилета',
            'статус',
            'цена'
        ]

        tickes_data = [
            [
                i['ticketUid'][:6],
                self._cut_datetime(i['date']),
                i['flightNumber'], 
                i['fromAirport'], 
                i['toAirport'], 
                self._pretty_status(i['status']), 
                i['price']
            ]
            for i in response.json()['tickets']
        ]

        return \
            f'билеты\n{tabulate(tickes_data, tickes_headers, "heavy_outline")}\n' \
            f'историая изменения баланса\n{tabulate(privilege_history_data, privilege_history_headers, "heavy_outline")}\n'\
            f'баланс: {response.json()["privilege"]["balance"]}\n'

    def bonus(self):
        response = requests.request(
            'GET',
            self._build_enpoint('privilege'),
            headers=self._authorization_header()
        )

        self._check_ok(response)
        self._check_json(response)
        
        history_headers = [
            'номер билета',
            'дата',
            'изменение баланса'
        ]

        history_data = [
            [
                i['ticketUid'][:6],
                self._cut_datetime(i['date']),
                f'{"+" if i["operationType"] == "FILL_IN_BALANCE" else "-"}{i["balanceDiff"]}'
            ]
            for i in response.json()['history']
        ]

        return \
            f'историая изменения баланса\n{tabulate(history_data, history_headers, "heavy_outline")}\n'\
            f'баланс: {response.json()["balance"]}\n'

    def _get_full_ticket_number(self, ticket_number):
        response = requests.request(
            'GET',
            self._build_enpoint('tickets'),
            headers=self._authorization_header()
        )

        self._check_ok(response)
        self._check_json(response)

        for i in response.json():
            if i['ticketUid'][:6] == ticket_number:
                return i['ticketUid']
    
        raise Exception(f'invlid ticket number: {ticket_number}')

    def _build_enpoint(self, path):
        return f'{self._url}/api/v1/{path}'

    def _check_ok(self, response, code=None):
        if 400 <= response.status_code:
            raise Exception(response.json()['message'])

        if code is not None and response.status_code != code:
            raise Exception(f'expected code: {code}')

    def _check_json(self, response):
        if not tools.is_json_content(response):
            raise Exception('expected json')

    def _authorization_header(self):
        return {'Authorization': f'Bearer {self._token}'}

    def _json_header(self):
        return {'Content-Type': 'application/json'}

    @staticmethod
    def _pretty_status(status):
        return 'оплачен' if status == 'PAID' else 'возвращен'

    @staticmethod
    def _cut_datetime(dt):
        return str(datetime.strptime(dt[:-7], '%a, %d %b %Y %H:%M'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--host', type=str, default='localhost')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--user', type=str, required=True)
    parser.add_argument('--password', type=str, required=True)
    parser.add_argument('action', type=str, nargs='?')

    cmd_args = parser.parse_args()

    action = cmd_args.action
    once = action is not None

    try:
        client = Client(
            cmd_args.host,
            cmd_args.port,
            cmd_args.user,
            cmd_args.password
        )

    except Exception as error:
        print(f'Failed create client, error: {error}')
        
        exit(-1)

    if action is None:
        action = input()

    while True:
        try:
            action = action.split()
            
            if len(action) != 0:
                if action[0] == '/q':
                    break

                elif action[0] == '/health':
                    response = client.health()

                elif action[0] == '/flights':
                    page = 1 if len(action) == 1 else action[1]

                    response = client.flights(page)

                elif action[0] == '/flight':
                    if len(action) != 2:
                        raise Exception('required flight number')
                    
                    response = client.flight(action[1])

                elif action[0] == '/tickets':
                    response = client.tickets()
                elif action[0] == '/ticket':
                    if len(action) != 2:
                        raise Exception('required ticket number')

                    response = client.ticket(action[1])

                elif action[0] == '/buy':
                    if len(action) != 3:
                        raise Exception('required flight number and paid from balance')
                    
                    paid_from_balance = True if action[2] == 'true' else False

                    response = client.buy_ticket(action[1], paid_from_balance)

                elif action[0] == '/return':
                    if len(action) != 2:
                        raise Exception('required ticket number')
                    
                    response = client.return_ticket(action[1])

                elif action[0] == '/me':
                    response = client.me()

                elif action[0] == '/bonus':
                    response = client.bonus()

                elif action[0] == '/register':
                    if len(action) != 3:
                        raise Exception('required username and password')
                    
                    response = client.register(action[1], action[2])

                else:
                    response = 'unknown operation'

                print(response)

        except Exception as error:
            print(f'Failed: {error}')

        if once:
            break

        action = input()
