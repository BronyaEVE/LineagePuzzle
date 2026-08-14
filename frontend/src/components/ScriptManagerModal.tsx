import React from "react";
import { Modal } from "antd";
import ScriptList from "./ScriptList";
import type { ScriptSummary, TagSchema } from "../types";

/**
 * 脚本管理弹窗（表为中心改造后脚本的归置地）。
 *
 * 脚本不再是主导航单元：日常「查血缘」从表出发；上传/重命名/删除/打标
 * 等管理动作收拢到这里（入口：顶栏「脚本管理」按钮）。ScriptList 仅保留
 * 管理能力（无导航/筛选职责，那些已随表为中心改造移到 TableList）。
 */

interface Props {
  open: boolean;
  onClose: () => void;
  scripts: ScriptSummary[];
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
  tagSchema: TagSchema;
  onSetScriptTags: (id: string, tags: string[]) => void;
  onBatchSetTags: (ids: string[], tags: string[]) => void;
}

const ScriptManagerModal: React.FC<Props> = ({
  open, onClose, scripts, onDelete, onRename, tagSchema, onSetScriptTags, onBatchSetTags,
}) => {
  return (
    <Modal
      title="脚本管理"
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnHidden
    >
      <div style={{ maxHeight: "60vh", overflow: "auto" }}>
        <ScriptList
          scripts={scripts}
          onDelete={onDelete}
          onRename={onRename}
          tagSchema={tagSchema}
          onSetScriptTags={onSetScriptTags}
          onBatchSetTags={onBatchSetTags}
        />
      </div>
    </Modal>
  );
};

export default ScriptManagerModal;
