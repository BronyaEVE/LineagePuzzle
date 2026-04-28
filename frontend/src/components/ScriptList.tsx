import React from "react";
import { Card, List, Typography, Button, Popconfirm, Input, Empty, Tag } from "antd";
import { DeleteOutlined, EditOutlined, FileTextOutlined } from "@ant-design/icons";
import type { ScriptSummary } from "../types";

const { Text } = Typography;

interface Props {
  scripts: ScriptSummary[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
}

const ScriptList: React.FC<Props> = ({ scripts, selectedId, onSelect, onDelete, onRename }) => {
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

  return (
    <Card
      title={
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span>脚本列表 ({scripts.length})</span>
          <Button
            size="small"
            type={selectedId === null ? "primary" : "default"}
            onClick={() => onSelect(null)}
          >
            全部
          </Button>
        </div>
      }
      size="small"
      style={{ height: "100%", overflow: "auto" }}
      styles={{ body: { padding: 0 } }}
    >
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
