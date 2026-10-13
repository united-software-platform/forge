--liquibase formatted sql

--changeset model-gen:baseline.1.2.0 labels:model-1.2.0
--comment: начальная схема модели forge.reqs 1.2.0
CREATE TYPE req_status AS ENUM ('DRAFT', 'APPROVED', 'RETIRED');
CREATE TYPE node_kind AS ENUM ('BR', 'FR');
CREATE TABLE model_state (
  version    text not null,
  hash       text not null
);
CREATE TABLE node (
  id         bigint generated always as identity primary key,
  kind       node_kind not null,
  code_num   integer not null check (code_num between 0 and 999),
  created_at timestamptz not null default now(),
  retired_at timestamptz,
  unique (kind, code_num),
  unique (id, kind)
);
CREATE VIEW node_code AS
  SELECT id, kind, code_num,
         kind::text || '-' || lpad(code_num::text, 3, '0') AS code
  FROM node;
CREATE TABLE node_revision (
  node_id    bigint not null references node(id),
  rev        integer not null check (rev > 0),
  mm_version integer not null,
  created_at timestamptz not null default now(),
  author     text not null,
  primary key (node_id, rev),
  unique (node_id, rev, mm_version)
);
CREATE TABLE rel_signature (
  rel        text not null,
  src_kind   node_kind not null,
  dst_kind   node_kind not null,
  src_min    integer not null default 0,
  src_max    integer,
  dst_min    integer not null default 0,
  dst_max    integer,
  acyclic    boolean not null default true,
  primary key (rel, src_kind, dst_kind)
);
CREATE TABLE link (
  id         bigint generated always as identity primary key,
  rel        text not null,
  src_id     bigint not null,
  src_kind   node_kind not null,
  dst_id     bigint not null,
  dst_kind   node_kind not null,
  conf_rev   integer not null,
  created_at timestamptz not null default now(),
  retired_at timestamptz,
  foreign key (src_id, src_kind) references node(id, kind),
  foreign key (dst_id, dst_kind) references node(id, kind),
  foreign key (rel, src_kind, dst_kind) references rel_signature,
  foreign key (dst_id, conf_rev) references node_revision(node_id, rev),
  unique (rel, src_id, dst_id)
);
CREATE TABLE br_revision (
  node_id    bigint not null,
  rev        integer not null,
  mm_version integer not null,
  kind       node_kind not null default 'BR' check (kind = 'BR'),
  title      text,
  value      text,
  status     req_status,
  origin     text,
  rationale  text,
  primary key (node_id, rev),
  foreign key (node_id, rev, mm_version) references node_revision(node_id, rev, mm_version),
  foreign key (node_id, kind) references node(id, kind)
);
ALTER TABLE br_revision ADD CONSTRAINT br_rationale_since_2
  CHECK (mm_version < 2 OR rationale IS NOT NULL) NOT VALID;
CREATE TABLE fr_revision (
  node_id    bigint not null,
  rev        integer not null,
  mm_version integer not null,
  kind       node_kind not null default 'FR' check (kind = 'FR'),
  title      text,
  status     req_status,
  primary key (node_id, rev),
  foreign key (node_id, rev, mm_version) references node_revision(node_id, rev, mm_version),
  foreign key (node_id, kind) references node(id, kind)
);
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('realizes', 'FR', 'BR', 1, null, 0, null, true);
--rollback -- начальная схема откатывается пересозданием хранилища
