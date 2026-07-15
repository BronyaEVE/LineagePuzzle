import React from "react";
import { Card, List, Typography, Button, Popconfirm, Input, Empty, Tag } from "antd";
import { DeleteOutlined, EditOutlined, FileTextOutlined, GlobalOutlined } from "@ant-design/icons";
import type { ScriptSummary } from "../types";
import { GLOBAL_ID } from "../types";

const { Text } = Typography;

interface Props {
  scripts: ScriptSummary[];
  selectedId: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
  /** 全局图谱的节点/边数（用于虚拟项显示统计） */
  tableCount?: number;
  edgeCount?: number;
}

const ScriptList: React.FC<Props> = ({ scripts, selectedId, onSelect, onDelete, onRename, tableCount, edgeCount }) => {
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [editName, setEditName] = React.useState("");

  const startRename = (id: string, currentName: string) => {
    setEditingId(id);
    setEditName(currentName);
  };

  const confirmRename = () => {
    if (editingId && editName.trim()) {
      onRename(editingId, editName.trim());
    }
    setEditingId(null);
  };

  // 全局图谱虚拟项（置顶，不可删除/重命名）
  const renderGlobalItem = () => {
    const isSelected = selectedId === GLOBAL_ID;
    return (
      <List.Item
        onClick={() => onSelect(GLOBAL_ID)}
        style={{
          cursor: "pointer",
          background: isSelected ? "#e6f7ff" : "#fafafa",
          borderLeft: isSelected ? "3px solid #1890ff" : "3px solid #1890ff",
          padding: "8px 12px",
          borderBottom: "1px solid #f0f0f0",
        }}
      >
        <div style={{ width: "100%" }}>
          <div style={{ marginBottom: 4 }}>
            <GlobalOutlined style={{ marginRight: 4, color: "#1890ff" }} />
            <Text strong style={{ fontSize: 13 }}>全局图谱</Text>
            <Tag color="blue" style={{ marginLeft: 6, fontSize: 10 }}>置顶</Tag>
          </div>
          {(tableCount !== undefined || edgeCount !== undefined) && (
            <div>
              {tableCount !== undefined && <Tag color="green" style={{ fontSize: 11 }}>{tableCount} 张表</Tag>}
              {edgeCount !== undefined && <Tag color="blue" style={{ fontSize: 11 }}>{edgeCount} 条血缘</Tag>}
            </div>
          )}
        </div>
      </List.Item>
    );
  };

  return (
    <Card
      title={<span>脚本列表 ({scripts.length})</span>}
      size="small"
      style={{ height: "100%", overflow: "auto" }}
      styles={{ body: { padding: 0 } }}
    >
      {/* 全局图谱虚拟项（始终置顶） */}
      {renderGlobalItem()}

      {scripts.length === 0 ? (
        <Empty description="暂无脚本" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 40 }} />
      ) : (
        <List
          size="small"
          dataSource={scripts}
          renderItem={(item) => {
            const isSelected = selectedId === item.analysis_id;
            const isEditing = editingId === item.analysis_id;

            return (
              <List.Item
                onClick={() => !isEditing && onSelect(item.analysis_id)}
                style={{
                  cursor: isEditing ? "default" : "pointer",
                  background: isSelected ? "#e6f7ff" : undefined,
                  borderLeft: isSelected ? "3px solid #1890ff" : "3px solid transparent",
                  padding: "8px 12px",
                  transition: "background 0.2s",
                }}
                actions={
                  isEditing
                    ? undefined
                    : [
                        <Button
                          key="rename"
                          type="text"
                          size="small"
                          icon={<EditOutlined />}
                          onClick={(e) => {
                            e.stopPropagation();
                            startRename(item.analysis_id, item.name);
                          }}
                        />,
                        <Popconfirm
                          key="delete"
                          title="确定删除该脚本？"
                          onConfirm={(e) => {
                            e?.stopPropagation();
                            onDelete(item.analysis_id);
                          }}
                          onCancel={(e) => e?.stopPropagation()}
                        >
                          <Button
                            type="text"
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </Popconfirm>,
                      ]
                }
              >
                <div style={{ width: "100%" }}>
                  {isEditing ? (
                    <Input
                      size="small"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onPressEnter={confirmRename}
                      onBlur={confirmRename}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <>
                      <div style={{ marginBottom: 4 }}>
                        <FileTextOutlined style={{ marginRight: 4, color: "#1890ff" }} />
                        <Text strong style={{ fontSize: 13 }}>{item.name}</Text>
                      </div>
                      <div>
                        <Tag color="blue" style={{ fontSize: 11 }}>{item.statement_count} 条语句</Tag>
                        <Tag color="green" style={{ fontSize: 11 }}>{item.table_count} 张表</Tag>
                      </div>
                      <div style={{ marginTop: 2 }}>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {new Date(item.created_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                        </Text>
                      </div>
                    </>
                  )}
                </div>
              </List.Item>
            );
          }}
        />
      )}
    </Card>
  );
};

export default ScriptList;
