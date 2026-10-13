--liquibase formatted sql

--changeset model-gen:TC.create labels:model-1.3.0
--comment: добавлен тип узла
CREATE TABLE tc_revision (
  node_id    bigint not null,
  rev        integer not null,
  mm_version integer not null,
  kind       node_kind not null default 'TC' check (kind = 'TC'),
  title      text,
  result     test_result,
  primary key (node_id, rev),
  foreign key (node_id, rev, mm_version) references node_revision(node_id, rev, mm_version),
  foreign key (node_id, kind) references node(id, kind)
);
--rollback DROP TABLE tc_revision;
