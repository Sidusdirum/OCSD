def format_time(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    parts = []
    if days:
        parts.append(f"{days} дн")
    if hours or days:
        parts.append(f"{hours} ч")
    if minutes or not parts:
        parts.append(f"{minutes} мин")
    return " ".join(parts)


def format_qty(qty: int) -> str:
    return f"{qty:,}".replace(",", " ")


def print_tree_visual(node, indent: str = "", last: bool = True) -> None:
    if isinstance(node, list):
        for i, n in enumerate(node):
            print_tree_visual(n, indent, i == len(node) - 1)
        return

    name = node.get('name', f"ID:{node['typeid']}")
    qty = node.get('qty', 1)
    marker = "[П]" if node.get('produce', False) else "[К]"

    prefix = "└── " if last else "├── "
    print(f"{indent}{prefix}{marker} {name} x{qty}")

    children = node.get('children', [])
    new_indent = indent + ("    " if last else "│   ")
    for i, child in enumerate(children):
        print_tree_visual(child, new_indent, i == len(children) - 1)