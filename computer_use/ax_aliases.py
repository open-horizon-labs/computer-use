"""Recognize redundant row/column projections of a complete AX table.

Equal names or coordinates alone never establish an alias. Require an entire
rectangular table's paired cell subtrees to match, including all observed
attributes and positive frames. Incomplete/spanned/mismatched grids abstain.
"""
import math

IDENTITY_FIELDS = {'element_index','element_token','parent_index','depth'}


def table_aliases(nodes):
    children = {}
    for index,node in nodes.items():
        children.setdefault(node.get('parent_index'),[]).append(index)

    def pair(row, column, visiting):
        if row in visiting or column in visiting:
            return None
        left,right=nodes[row],nodes[column]
        for node in (left,right):
            frame=node.get('frame',{})
            if (set(frame)!={'x','y','w','h'} or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in frame.values())
                    or frame['w']<=0 or frame['h']<=0):return None
        if {k:v for k,v in left.items() if k not in IDENTITY_FIELDS}!={k:v for k,v in right.items() if k not in IDENTITY_FIELDS}:return None
        a,b=children.get(row,[]),children.get(column,[])
        if len(a)!=len(b):return None
        result={column:row}
        for x,y in zip(a,b):
            nested=pair(x,y,visiting|{row,column})
            if nested is None:return None
            result.update(nested)
        return result

    aliases={}
    for table,node in nodes.items():
        if node.get('role')!='AXTable':continue
        rows=[i for i in children.get(table,[]) if nodes[i].get('role')=='AXRow']
        columns=[i for i in children.get(table,[]) if nodes[i].get('role')=='AXColumn']
        if not rows or not columns:continue
        row_cells=[children.get(i,[]) for i in rows]
        col_cells=[children.get(i,[]) for i in columns]
        if any(len(c)!=len(columns) for c in row_cells) or any(len(c)!=len(rows) for c in col_cells):continue
        if any(nodes[i].get('role')!='AXCell' for cells in row_cells+col_cells for i in cells):continue
        proposed={};valid=True
        for r,cells in enumerate(row_cells):
            for c,cell in enumerate(cells):
                mapping=pair(cell,col_cells[c][r],set())
                if mapping is None:valid=False;break
                proposed.update(mapping)
            if not valid:break
        if valid:aliases.update(proposed)
    return aliases
