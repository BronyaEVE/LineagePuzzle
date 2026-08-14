import React from "react";
import { Card, List, Typography, Button, Popconfirm, Input, Empty, Tag } from "antd";
import { DeleteOutlined, EditOutlined, FileTextOutlined } from "@ant-design/icons";
import type { ScriptSummary } from "../types";

const { Text } = Typography;

/**
 * 脚本管理列表（仅在「脚本管理」弹窗内使用）。
 *
 * 表为中心改造后脚本不再是导航单元：本组件只保留管理能力
 * （列表 / 重命名 / 删除）。旧的左栏职责（全局图谱虚拟项、标签筛选、
 * 选中导航）已随导航迁移到 TableList；打标 UI 已按需求移除——
 * 标签仅在批量导入时指定，表列表的标签筛选消费导入时打的标签。
 */
interface Props {
  scripts: ScriptSummary[];
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
}

const ScriptList: React.FC<Props> = ({ scripts, onDelete, onRename }) => {
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
      title={<span>脚本列表 ({scripts.length})</span>}
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
            const isEditing = editingId === item.analysis_id;

            return (
              <List.Item
                style={{ padding: "8px 12px" }}
                actions={
                  isEditing
                    ? undefined
                    : [
                        <Button
                          key="rename"
                          type="text"
                          size="small"
                          icon={<EditOutlined />}
                          onClick={() => startRename(item.analysis_id, item.name)}
                        />,
                        <Popconfirm
                          key="delete"
                          title="确定删除该脚本？"
                          onConfirm={() => onDelete(item.analysis_id)}
                        >
                          <Button
                            type="text"
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                          />
                        </Popconfirm>,
                      ]
                }
              >
                <div style={{ width: "100%", minWidth: 0 }}>
                  {isEditing ? (
                    <Input
                      size="small"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      onPressEnter={confirmRename}
                      onBlur={confirmRename}
                      autoFocus
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
