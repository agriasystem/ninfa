-- Creates the NINFA application role and the development/test databases. Idempotent.
-- The application never uses a superuser: it connects as `ninfa_app` (no SUPERUSER/CREATEDB/
-- CREATEROLE) which owns both databases and can therefore run Alembic migrations in them.
--
-- Run once as a PostgreSQL superuser (you will be asked for that password by psql):
--   psql -h 127.0.0.1 -U postgres -v app_password='<password used in DATABASE_URL>' \
--        -f scripts/db/bootstrap-local.sql
\set ON_ERROR_STOP on

SELECT format('CREATE ROLE ninfa_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ninfa_app') \gexec

SELECT 'CREATE DATABASE ninfa_dev OWNER ninfa_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ninfa_dev') \gexec

SELECT 'CREATE DATABASE ninfa_test OWNER ninfa_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ninfa_test') \gexec
