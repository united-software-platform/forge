--liquibase formatted sql

--changeset model-gen:close.1.3.0 labels:model-1.3.0
--comment: 1.2.0 -> 1.3.0
--preconditions onFail:HALT
--precondition-sql-check expectedResult:1 SELECT count(*) FROM model_state WHERE hash = 'sha256:75628d78d447f9b0731f4b1879bbf6e3f88961050eb9eaaece117f72b59031da'
UPDATE model_state SET version = '1.3.0', hash = 'sha256:13c6c202aa65b263719b42f10878a1bde954033d508b9f458f4d4789d3cfcb91';
--rollback -- откат версии выполняется откатом миграций этой версии
