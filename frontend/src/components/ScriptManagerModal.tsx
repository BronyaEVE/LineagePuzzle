import React from "react";
import { Modal } from "antd";
import ScriptList from "./ScriptList";
import type { ScriptSummary, TagSchema } from "../types";
import { GLOBAL_ID } from "../types";

/**
 * 脚本管理弹窗（表为中心改造后脚本的归置地）。
 *
 * 脚本不再是主导航单元：日常「查血缘」从表出发；上传/重命名/删除/打标
 * 等管理动作收拢到这里（入口：顶栏「脚本管理」按钮）。内部复用
 * ScriptList 全部能力，仅隐藏全局图谱虚拟项和标签筛选器（筛选已随
 * 导航移到表列表）。
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
      {/* 选中态用 GLOBAL_ID：弹窗内没有「选中导航」语义，仅避免脚本列表项误高亮 */}
      <div style={{ maxHeight: "60vh", overflow: "auto" }}>
        <ScriptList
          scripts={scripts}
          selectedId={GLOBAL_ID}
          onSelect={() => {/* 弹窗内点击不切换视图；语句查看走表详情的相关脚本 */}}
          onDelete={onDelete}
          onRename={onRename}
          tagSchema={tagSchema}
          selectedTags={[]}
          onSelectedTagsChange={() => {}}
          hitScriptIds={new Set<string>()}
          isGlobalView={false}
          onSetScriptTags={onSetScriptTags}
          onBatchSetTags={onBatchSetTags}
          showGlobalItem={false}
          showTagFilter={false}
        />
      </div>
    </Modal>
  );
};

export default ScriptManagerModal;
