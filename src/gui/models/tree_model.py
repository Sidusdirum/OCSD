from PySide6.QtCore import Qt, QAbstractItemModel, QModelIndex
from typing import List, Dict, Any, Optional


class TreeNode:
    """Вспомогательный класс для хранения данных узла в модели."""
    def __init__(self, data: Dict[str, Any], parent: Optional['TreeNode'] = None):
        self.data = data
        self.parent = parent
        self.children: List['TreeNode'] = []
        self.is_expanded = False # По умолчанию свернуто (покупаем)

    def row(self) -> int:
        if self.parent:
            return self.parent.children.index(self)
        return 0


class ProductionTreeModel(QAbstractItemModel):
    def __init__(self, headers: List[str], parent=None):
        super().__init__(parent)
        self.headers = headers
        self.root_node = TreeNode({"name": "Root"})
        self._expanded_state: Dict[int, bool] = {} # Храним состояние {typeid: expanded}

    def set_tree_data(self, tree_data: List[Dict[str, Any]]):
        """Загружает данные из дерева (список словарей) в модель."""
        self.beginResetModel()
        self.root_node.children.clear()

        def add_nodes(nodes: List[Dict[str, Any]], parent: TreeNode):
            for node_data in nodes:
                new_node = TreeNode(node_data, parent)
                # Восстанавливаем состояние из сохраненного словаря, если есть
                tid = node_data.get("typeid")
                if tid in self._expanded_state:
                    new_node.is_expanded = self._expanded_state[tid]

                parent.children.append(new_node)

                # Рекурсивно добавляем детей
                if node_data.get("children"):
                    add_nodes(node_data["children"], new_node)

        add_nodes(tree_data, self.root_node)
        self.endResetModel()

    def update_expanded_state(self, typeid: int, is_expanded: bool):
        """Обновляет сохраненное состояние раскрытия."""
        self._expanded_state[typeid] = is_expanded

    # --- Обязательные методы для QAbstractItemModel ---

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_node = self.node_from_index(parent)
        if parent_node and row < len(parent_node.children):
            return self.createIndex(row, column, parent_node.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()

        child_node = self.node_from_index(index)
        parent_node = child_node.parent

        if parent_node == self.root_node or parent_node is None:
            return QModelIndex()

        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        node = self.node_from_index(parent)
        return len(node.children) if node else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None

        node = self.node_from_index(index)
        col = index.column()

        if role == Qt.DisplayRole or role == Qt.UserRole:
            if col == 0:
                return node.data.get("name", "Unknown")
            elif col == 1:
                return node.data.get("qty", 0)
            return ""

        if role == Qt.TextAlignmentRole:
            if col > 0:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None

    def node_from_index(self, index: QModelIndex) -> Optional[TreeNode]:
        if index.isValid():
            return index.internalPointer()
        return self.root_node