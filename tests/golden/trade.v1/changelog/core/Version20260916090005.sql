--liquibase formatted sql

--changeset model-gen:close.1.1.0 labels:model-1.1.0
--comment: 1.0.0 -> 1.1.0
--preconditions onFail:HALT
--precondition-sql-check expectedResult:1 SELECT count(*) FROM model_state WHERE hash = 'sha256:5d31ce8efb3dc7f677da9f0b86279515a743d7a06ff2bb5ffd60af7a737bb08c'
UPDATE model_state SET version = '1.1.0', hash = 'sha256:1cdc8e4eb175eb3e378aa625e33bc25fe31d2c7f5e5302f8f560832fadf4d951';
--rollback -- откат версии выполняется откатом миграций этой версии
