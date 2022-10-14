CREATE TABLE IF NOT EXISTS room (
	time		TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
    name        VARCHAR   NOT NULL,
    temperature REAL,
    humidity    REAL,
    shading     REAL,
    valve       REAL,
    ventilation BOOLEAN,
	UNIQUE		(time, name)
);
