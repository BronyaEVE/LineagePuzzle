import React from "react";
import { Modal } from "antd";
import ScriptList from "./ScriptList";
import type { ScriptSummary } from "../types";

/**
 * 脚本管理弹窗（表为中心改造后脚本的归置地）。
 *
 * 脚本不再是主导航单元：日常「查血缘」从表出发；重命名/删除等管理
 * 动作收拢到这里（入口：顶栏「脚本管理」按钮）。打标 UI 已移除——
 * 标签仅在批量导入时指定。
 */

interface Props {
  open: boolean;
  onClose: () => void;
  scripts: ScriptSummary[];
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
}

const ScriptManagerModal: React.FC<Props> = ({
  open, onClose, scripts, onDelete, onRename,
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
        />
      </div>
    </Modal>
  );
};

export default ScriptManagerModal;
