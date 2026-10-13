--liquibase formatted sql

--changeset model-gen:close.1.0.0 labels:model-1.0.0
--comment: отпечаток модели 1.0.0
INSERT INTO model_state (version, hash) VALUES ('1.0.0', 'sha256:5d31ce8efb3dc7f677da9f0b86279515a743d7a06ff2bb5ffd60af7a737bb08c');
--rollback -- откат версии выполняется откатом миграций этой версии
