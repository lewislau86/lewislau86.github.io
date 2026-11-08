CREATE TABLE settings (
    id integer PRIMARY KEY CHECK(id=1), schema integer NOT NULL,
    release text NOT NULL, draining boolean NOT NULL DEFAULT false,
    approved boolean NOT NULL DEFAULT false, recovery boolean NOT NULL DEFAULT false,
    active integer NOT NULL DEFAULT 0, capacity integer NOT NULL DEFAULT 4,
    admitted bigint NOT NULL DEFAULT 0, rejected bigint NOT NULL DEFAULT 0,
    finished bigint NOT NULL DEFAULT 0, CHECK(active>=0 AND active<=capacity)
);
INSERT INTO settings(id,schema,release) VALUES(1,1,'p04-v2');
CREATE TABLE sessions(tenant text, id text, version integer NOT NULL, payload jsonb NOT NULL,
    PRIMARY KEY(tenant,id));
INSERT INTO sessions VALUES('a','session',1,'{"next":"review","spent":3}');
INSERT INTO sessions VALUES('b','session',1,'{"next":"private","spent":9}');
CREATE TABLE approvals(tenant text, id text, revision bigint, approved boolean NOT NULL DEFAULT false,
    PRIMARY KEY(tenant,id));
INSERT INTO approvals(tenant,id,revision) VALUES('a','action',7);
CREATE TABLE jobs(id text PRIMARY KEY,state text NOT NULL CHECK(state IN ('running','done')));
CREATE TABLE lease(id integer PRIMARY KEY CHECK(id=1),owner text,epoch bigint NOT NULL,
    deadline timestamptz);
INSERT INTO lease VALUES(1,NULL,0,NULL);
CREATE TABLE results(id text PRIMARY KEY,owner text NOT NULL,epoch bigint NOT NULL);
