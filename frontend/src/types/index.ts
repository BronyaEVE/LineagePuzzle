// === Request Types ===

export interface DatabaseConfig {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
}

export interface AnalyzeRequest {
  script: string;
  database_config: DatabaseConfig;
}

export interface CorrectStatementRequest {
  corrected_text: string;
  tables_referenced: string[];
  tables_modified: string[];
}

// === Response Types ===

export type StatementType = "CREATE" | "INSERT" | "UPDATE" | "DELETE" | "MERGE" | "UNKNOWN";
export type TableType = "source" | "intermediate" | "target";
export type ExtractionMethod = "execution_plan" | "static_analysis";
export type OperationType = "CREATE" | "INSERT" | "UPDATE" | "DELETE" | "MERGE";

export interface Statement {
  seq: number;
  type: StatementType;
  text: string;
  tables_referenced: string[];
  tables_created: string[];
  tables_modified: string[];
}

export interface StatementGroup {
  group_id: string;
  original_script: string;
  preprocessed_script: string;
  statements: Statement[];
}

export interface ColumnInfo {
  name: string;
  type: string;
}

export interface TableInfo {
  schema_name: string;
  table_name: string;
  table_type: TableType;
  source: string;
  columns: ColumnInfo[];
}

export interface ColumnMapping {
  source_column: string;
  target_column: string;
  transformation?: string;
}

export interface Lineage {
  lineage_id: string;
  source_table: string;
  target_table: string;
  operation_type: OperationType;
  extraction_method: ExtractionMethod;
  statement_seq: number;
  column_mappings: ColumnMapping[];
  dml_statement: string;
}

export interface DatabaseInfo {
  tables_from_db: TableInfo[];
  tables_from_script: TableInfo[];
}

export interface VisNode {
  id: string;
  label: string;
  type: TableType;
}

export interface VisEdge {
  source: string;
  target: string;
  label: string;
  statement_seq: number;
}

export interface Visualization {
  nodes: VisNode[];
  edges: VisEdge[];
}

export interface AnalysisResult {
  analysis_id: string;
  created_at: string;
  input_script: string;
  database_info: DatabaseInfo;
  statement_group: StatementGroup | null;
  lineages: Lineage[];
  visualization: Visualization;
}
