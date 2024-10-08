CREATE DATABASE flights;
\c flights;

CREATE TABLE airport
(
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(255),
    city    VARCHAR(255),
    country VARCHAR(255)
);

CREATE TABLE flight
(
    id              SERIAL PRIMARY KEY,
    number          VARCHAR(20)              NOT NULL,
    datetime        TIMESTAMP WITH TIME ZONE NOT NULL,
    from_airport_id INT REFERENCES airport (id),
    to_airport_id   INT REFERENCES airport (id),
    price           INT                      NOT NULL
);

INSERT INTO airport(name, city, country) VALUES ('Шереметьево', 'Москва', 'Россия');
INSERT INTO airport(name, city, country) VALUES ('Пулково', 'Санкт-Петербург', 'Россия');
INSERT INTO flight(number, datetime, from_airport_id, to_airport_id, price)
VALUES ('AFL031', '2021-10-08 20:00', 2, 1, 1500);

CREATE DATABASE tickets;
\c tickets;

CREATE TABLE ticket
(
    id            SERIAL PRIMARY KEY,
    uid           uuid UNIQUE NOT NULL,
    username      VARCHAR(80) NOT NULL,
    flight_number VARCHAR(20) NOT NULL,
    price         INT         NOT NULL,
    status        VARCHAR(20) NOT NULL CHECK (status IN ('PAID', 'CANCELED'))
);


CREATE DATABASE privileges;
\c privileges;

CREATE TABLE privilege
(
    id       SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    status   VARCHAR(80) NOT NULL DEFAULT 'BRONZE' CHECK (status IN ('BRONZE', 'SILVER', 'GOLD')),
    balance  INT
);

CREATE TABLE privilege_history
(
    id             SERIAL PRIMARY KEY,
    privilege_id   INT REFERENCES privilege (id),
    ticket_uid     uuid        NOT NULL,
    datetime       TIMESTAMP   NOT NULL,
    balance_diff   INT         NOT NULL,
    operation_type VARCHAR(20) NOT NULL CHECK (operation_type IN ('FILL_IN_BALANCE', 'DEBIT_THE_ACCOUNT'))
);

CREATE DATABASE keycloak;
\c keycloak;

CREATE DATABASE stats;
\c stats;

CREATE TABLE stat
(
    id      SERIAL PRIMARY KEY,
    service VARCHAR(80) NOT NULL,
    path    VARCHAR(80) NOT NULL,
    method  VARCHAR(80) NOT NULL CHECK (method IN ('GET', 'POST', 'DELETE')),
    count   INT         NOT NULL DEFAULT 0,
    UNIQUE(service, method, path)
)
