CREATE TABLE IF NOT EXISTS room (
    time               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
    id                 VARCHAR   NOT NULL,
    name               VARCHAR   NOT NULL,
    temperature        REAL,
    temperature_target REAL,
    humidity           REAL,
    light              BOOLEAN,
    shading            REAL,
    valve              REAL,
    ventilation        BOOLEAN,
    precence           BOOLEAN,
    UNIQUE             (time, id)
);

CREATE TABLE IF NOT EXISTS weather (
    time   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
    UNIQUE (time)
);

CREATE TABLE IF NOT EXISTS electricity (
    time      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
    id        VARCHAR   NOT NULL,
    name      VARCHAR   NOT NULL,
    energy_l1 REAL,
    energy_l2 REAL,
    energy_l3 REAL,
    UNIQUE    (time, id)
);
