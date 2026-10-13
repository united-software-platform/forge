--liquibase formatted sql

--changeset model-gen:close.1.3.0 labels:model-1.3.0
--comment: 1.2.0 -> 1.3.0; схема не меняется
--preconditions onFail:HALT
--precondition-sql-check expectedResult:1 SELECT count(*) FROM model_state WHERE hash = 'sha256:1da6900a4dd441e5d62fd4742356676017d711de75293b7037dc09757e127ba3'
UPDATE model_state SET version = '1.3.0', hash = 'sha256:0c4324889a47bdbca27a094b0dfe177285b555c85961fd2018860a8c46a6f12f';
--rollback -- откат версии выполняется откатом миграций этой версии
