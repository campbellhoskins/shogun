import '../styles/EntityChip.css';

interface Props {
  name: string;
  type?: string;
  color?: string;
  onClick?: () => void;
}

export default function EntityChip({ name, type, color, onClick }: Props) {
  return (
    <span
      className="entity-chip"
      onClick={onClick}
      style={color ? { borderColor: color + '30' } : undefined}
      title={type ? `${name} [${type}]` : name}
    >
      {color && <span className="entity-chip-dot" style={{ backgroundColor: color }} />}
      <span className="entity-chip-name">{name}</span>
    </span>
  );
}
