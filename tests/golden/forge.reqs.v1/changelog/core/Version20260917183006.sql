--liquibase formatted sql

--changeset model-gen:close.1.4.0 labels:model-1.4.0
--comment: 1.3.0 -> 1.4.0
--preconditions onFail:HALT
--precondition-sql-check expectedResult:1 SELECT count(*) FROM model_state WHERE hash = 'sha256:13c6c202aa65b263719b42f10878a1bde954033d508b9f458f4d4789d3cfcb91'
UPDATE model_state SET version = '1.4.0', hash = 'sha256:e61c3a6b00b3bb046cd4e7eae8505547b104ac3b637031b313dece90c74bf19b';
--rollback -- откат версии выполняется откатом миграций этой версии
