--liquibase formatted sql

--changeset model-gen:close.1.2.0 labels:model-1.2.0
--comment: 1.1.0 -> 1.2.0
--preconditions onFail:HALT
--precondition-sql-check expectedResult:1 SELECT count(*) FROM model_state WHERE hash = 'sha256:1cdc8e4eb175eb3e378aa625e33bc25fe31d2c7f5e5302f8f560832fadf4d951'
UPDATE model_state SET version = '1.2.0', hash = 'sha256:1da6900a4dd441e5d62fd4742356676017d711de75293b7037dc09757e127ba3';
--rollback -- откат версии выполняется откатом миграций этой версии
